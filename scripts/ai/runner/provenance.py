"""사용할 site 산출물의 출처 확인과 결과의 code 블록 구성."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .config import REPO_ROOT, RunConfig


class BuildError(Exception):
    """산출물 없음·출처 불일치·빌드 종류 불일치(종료 코드 3)."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True,
                             errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def main_commit_and_dirty() -> tuple[str | None, list[str] | None]:
    """실행기 checkout의 커밋과 미커밋 변경. git status가 실패하면 빈 목록(clean)이 아니라 None(확인 불가)."""
    commit = (_git("rev-parse", "HEAD") or "").strip() or None
    dirty_raw = _git("status", "--porcelain")
    if dirty_raw is None:
        return commit, None
    return commit, [line for line in dirty_raw.splitlines() if line.strip()]


def inspect_site(cfg: RunConfig, site: Path) -> dict:
    """site를 검사하고 결과의 code 블록 재료를 돌려준다. 문제가 있으면 BuildError."""
    if not site.is_dir():
        raise BuildError(f"site 디렉터리가 없습니다: {site}\n  먼저 scripts/build-web.ps1"
                         f"{' -Flavor developer' if cfg.build_flavor == 'developer' else ''}를 실행하세요.")
    info_path = site / "build-info.json"
    if not info_path.is_file():
        raise BuildError(f"build-info.json이 없어 산출물의 출처를 알 수 없습니다: {info_path}")
    try:
        info = json.loads(info_path.read_text(encoding="utf-8-sig"))
        build = info["build"]
        site_info = info["site"]
    except (ValueError, KeyError, TypeError) as exc:
        raise BuildError(f"build-info.json 형식이 올바르지 않습니다: {exc!r}") from exc

    # flavor 필드가 없는 기록은 이 필드가 생기기 전에 만든 릴리스 빌드다.
    recorded_flavor = build.get("flavor", "release")
    if recorded_flavor != cfg.build_flavor:
        raise BuildError(f"빌드 종류 불일치: 요청 {cfg.build_flavor}, build-info.json 기록 {recorded_flavor}"
                         f" ({site})")
    if (cfg.stage or cfg.spell) and recorded_flavor != "developer":
        raise BuildError("--stage/--spell로 바로 시작하는 인자(--sid 등)는 개발자 빌드에만 있습니다. "
                         "--build-flavor developer와 build/web-dev/site를 사용하세요.")

    entry = site_info.get("entry", "game/index.html")
    if not (site / entry).is_file():
        raise BuildError(f"진입 파일이 없습니다: {site / entry}")
    wasm = site / "game" / "taisei.wasm"
    if not wasm.is_file():
        raise BuildError(f"taisei.wasm이 없습니다: {wasm}")
    wasm_sha = sha256_file(wasm)
    recorded_wasm = (site_info.get("sha256") or {}).get("game/taisei.wasm")
    if recorded_wasm and recorded_wasm != wasm_sha:
        raise BuildError("game/taisei.wasm 해시가 build-info.json 기록과 다릅니다(산출물이 바뀌었거나 손상됨)")
    if not recorded_wasm:
        raise BuildError("build-info.json에 game/taisei.wasm 해시 기록이 없습니다")

    return {
        "entry": entry,
        "build_info_sha256": sha256_file(info_path),
        "wasm_sha256": wasm_sha,
        "build_flavor": recorded_flavor,
        "meson_options": build.get("mesonOptions"),
        "rules_preserved": build.get("rulesPreserved", "unverified" if recorded_flavor == "developer" else "original"),
        "taisei_commit": build.get("taiseiCommit"),
        "build_repository_commit": build.get("repositoryCommit"),
        "build_started_at": build.get("buildStartedAtUtc"),
        # 빌드·패키징 시점의 미커밋 변경. 기록에 없으면 None(확인 불가)이다.
        "build_dirty_entries": build.get("repositoryDirtyEntries"),
        "build_taisei_dirty_entries": build.get("taiseiWorktreeDirtyEntries"),
        "packaging_dirty_entries": (info.get("packaging") or {}).get("repositoryDirtyEntries"),
        "web_shell_dirty_entries": (info.get("packaging") or {}).get("webShellDirtyEntries"),
    }


def aggregate_dirty(sources: dict) -> bool | None:
    """재현 가능 여부 합산: 어느 출처든 변경이 있으면 True, 확인 불가(None)가 하나라도 있으면 None, 모두 비어 있어야 False."""
    if any(isinstance(v, list) and v for v in sources.values()):
        return True
    if any(not isinstance(v, list) for v in sources.values()):
        return None
    return False


def code_block(site_facts: dict, main_commit: str | None, dirty: list[str] | None) -> dict:
    # 실행기 코드·빌드 소스·Taisei 작업 트리·패키징 입력·웹 셸을 구분해 모두 남기고 합산한다.
    sources = {
        "runner_checkout": dirty,
        "build_repository": site_facts["build_dirty_entries"],
        "build_taisei_worktree": site_facts["build_taisei_dirty_entries"],
        "packaging_repository": site_facts["packaging_dirty_entries"],
        "web_shell": site_facts["web_shell_dirty_entries"],
    }
    return {
        "main_commit": main_commit,
        "dirty": aggregate_dirty(sources),
        "dirty_entries": dirty,
        "dirty_sources": sources,
        "taisei_commit": site_facts["taisei_commit"],
        "build_flavor": site_facts["build_flavor"],
        "meson_options": site_facts["meson_options"],
        "rules_preserved": site_facts["rules_preserved"],
        "build_info_sha256": site_facts["build_info_sha256"],
        "wasm_sha256": site_facts["wasm_sha256"],
        "build_repository_commit": site_facts["build_repository_commit"],
        "build_started_at": site_facts["build_started_at"],
    }
