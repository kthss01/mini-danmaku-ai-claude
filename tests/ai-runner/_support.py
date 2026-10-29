"""실행기 테스트 공용 도구: fixture site 만들기, 실행기 호출, 누수 확인."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
RUN_PY = REPO_ROOT / "scripts" / "ai" / "run.py"
FIXTURE_DIR = HERE / "fixture"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "ai"))
from runner import procs  # noqa: E402
from runner.browser import find_browser  # noqa: E402

PROFILE_MARKER = "taisei-ai-profile-"
CHROME = find_browser("chrome") or find_browser("msedge")


def make_site(root: Path, flavor: str = "release", wasm_bytes: bytes = b"\0asm-fixture") -> Path:
    """fixture 페이지와 build-info.json을 가진 site 디렉터리를 만든다."""
    site = root / "site"
    shutil.copytree(FIXTURE_DIR, site)
    (site / "game" / "taisei.wasm").write_bytes(wasm_bytes)
    (site / "index.html").write_text("<!doctype html><title>fixture</title>", encoding="utf-8")
    info = {
        "schema": 1,
        "build": {
            "schema": 1, "flavor": flavor, "mesonOptions": ["-Dbuild.cpp_std=gnu++14"] + (["-Ddeveloper=true"] if flavor == "developer" else []),
            "rulesPreserved": "unverified" if flavor == "developer" else "original",
            "buildStartedAtUtc": "2026-10-29T00:00:00Z", "taiseiCommit": "f" * 40, "repositoryCommit": "e" * 40,
            "repositoryDirtyEntries": [], "taiseiWorktreeDirtyEntries": [],
        },
        "packaging": {"repositoryDirtyEntries": [], "webShellDirtyEntries": []},
        "site": {"entry": "game/index.html",
                 "sha256": {"game/taisei.wasm": hashlib.sha256(wasm_bytes).hexdigest()}},
    }
    (site / "build-info.json").write_text(json.dumps(info), encoding="utf-8")
    return site


def run_cli(args: list[str], run_root: Path, timeout: float = 120.0, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(RUN_PY), "--run-root", str(run_root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, **kwargs,
    )


def last_run_dir(run_root: Path) -> Path:
    dirs = sorted(p for p in run_root.iterdir() if p.is_dir())
    assert dirs, f"실행 폴더가 없습니다: {run_root}"
    return dirs[-1]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def leftover_profiles() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob(PROFILE_MARKER + "*")}


def leftover_browser_pids() -> list[int]:
    return procs.find_pids_by_cmdline(PROFILE_MARKER)
