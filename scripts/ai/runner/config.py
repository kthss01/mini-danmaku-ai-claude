"""실행 인자 검증과 종료 코드. 계약은 docs/ai/RUNNER.md."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# 종료 코드: 실행 전체가 어떻게 끝났는지만 말한다. 에피소드 상태는 에피소드 파일의 run.status로 본다.
EXIT_OK = 0
EXIT_BAD_ARGS = 2        # 인자·설정 오류, 미지원 옵션. 실행 시작 전
EXIT_BAD_BUILD = 3       # 산출물 없음·출처 불일치·빌드 종류 불일치. 실행 시작 전
EXIT_NO_START = 4        # 서버·브라우저·페이지를 띄우지 못해 에피소드를 시작하지 못함
EXIT_RUNNER_ERROR = 5    # 실행 도중 실행기 내부 오류로 남은 에피소드를 시도하지 못함
EXIT_CLEANUP_FAILED = 6  # 에피소드는 끝났지만 프로세스·포트·입력 정리에 실패(누수)
EXIT_ABORTED = 130       # 사용자 중단

DIFFICULTIES = ("Easy", "Normal", "Hard", "Lunatic")
SHOTMODES = ("marisaA", "marisaB", "youmuA", "youmuB")
MODES = ("bridge", "smoke")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ArgError(Exception):
    """인자·설정 오류(종료 코드 2)."""


@dataclass
class RunConfig:
    experiment_id: str = "adhoc"
    mode: str = "bridge"
    policy: str = "none"
    policy_version: str = ""
    policy_params: dict = field(default_factory=dict)
    difficulty: str = "Easy"
    shotmode: str = ""
    stage: str = ""
    spell: str = ""
    seed: int | None = None
    max_frames: int = 3600
    wall_timeout_s: float = 180.0
    startup_timeout_s: float = 120.0
    smoke_duration_s: float = 5.0
    episodes: int = 1
    build_flavor: str = "release"
    site: str = ""
    browser: str = "chrome"
    headless: bool = True
    port: int = 0
    run_root: str = ""
    shot_inverted: int | None = None

    def scenario(self) -> dict:
        # shotmode(예: marisaA)를 세션 4 스키마의 character(marisa)와 shot(A)로 나누어 함께 기록한다.
        character = self.shotmode[:-1] if self.shotmode else None
        shot = self.shotmode[-1] if self.shotmode else None
        base = {"difficulty": self.difficulty, "character": character, "shot": shot, "shotmode": self.shotmode or None}
        if self.spell:
            return {"kind": "spell", "id": self.spell, **base}
        if self.stage:
            return {"kind": "stage", "id": self.stage, **base}
        # 대상을 지정하지 않은 실행(smoke 등). 세션 4 스키마의 kind에 없어 "menu"를 추가해 달라고 요청한다(#23).
        return {"kind": "menu", "id": None, **base}

    def game_args(self) -> list[str]:
        """개발자 빌드에서 게임 main에 넘길 인자. 셸이 callMain(args)로 전달해야 효과가 있다(세션 5 조정)."""
        args: list[str] = []
        if self.stage or self.spell:
            args += ["--sid", self.spell or self.stage, "--diff", self.difficulty]
        if self.shotmode:
            args += ["--shotmode", self.shotmode]
        return args

    def default_site(self) -> Path:
        directory = "web-dev" if self.build_flavor == "developer" else "web"
        return REPO_ROOT / "build" / directory / "site"


_INT_KEYS = ("max_frames", "episodes", "port", "shot_inverted")
_FLOAT_KEYS = ("wall_timeout_s", "startup_timeout_s", "smoke_duration_s")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run.py",
        description="Taisei 웹 빌드로 AI 실험을 실행한다. 시작·감시·수집만 하며 정책은 페이지 안에서 돈다.",
        epilog="종료 코드: 0 완료, 2 인자 오류, 3 산출물 오류, 4 시작 실패, 5 실행기 오류, 6 정리 실패, 130 중단",
    )
    p.add_argument("--config", help="JSON 설정 파일(키는 아래 옵션 이름과 같다. 명령줄이 우선한다)")
    p.add_argument("--experiment-id", dest="experiment_id")
    p.add_argument("--mode", choices=MODES, help="bridge: 브리지와 에피소드 실행(기본). smoke: 셸이 playing에 이르는지만 확인")
    p.add_argument("--policy", help="정책 식별자(페이지 안에서 불러온다)")
    p.add_argument("--policy-version", dest="policy_version")
    p.add_argument("--policy-params", dest="policy_params", help="정책 파라미터 JSON 문자열 또는 파일 경로")
    p.add_argument("--difficulty", choices=DIFFICULTIES)
    p.add_argument("--shotmode", choices=SHOTMODES)
    target = p.add_mutually_exclusive_group()
    target.add_argument("--stage", help="대상 스테이지 ID(개발자 빌드 필요)")
    target.add_argument("--spell", help="대상 스펠 ID(개발자 빌드 필요)")
    p.add_argument("--seed", type=int, help="현재 미지원. 지정하면 종료 코드 2")
    p.add_argument("--max-frames", dest="max_frames", type=int, help="논리 프레임 한도(페이지가 집행)")
    p.add_argument("--wall-timeout-s", dest="wall_timeout_s", type=float, help="에피소드당 벽시계 한도(초)")
    p.add_argument("--startup-timeout-s", dest="startup_timeout_s", type=float, help="페이지가 playing에 이르기까지의 한도(초)")
    p.add_argument("--smoke-duration-s", dest="smoke_duration_s", type=float, help="smoke 모드에서 playing 이후 지켜볼 시간(초)")
    p.add_argument("--episodes", type=int, help="연속 에피소드 수")
    p.add_argument("--build-flavor", dest="build_flavor", choices=("release", "developer"), help="사용할 빌드 종류(기본 release)")
    p.add_argument("--site", help="서빙할 site 디렉터리(기본: 빌드 종류별 build/web[-dev]/site)")
    p.add_argument("--browser", help="chrome, msedge 또는 실행 파일 경로(기본 chrome)")
    head = p.add_mutually_exclusive_group()
    head.add_argument("--headless", dest="headless", action="store_const", const=True)
    head.add_argument("--headed", dest="headless", action="store_const", const=False)
    p.add_argument("--port", type=int, help="서버 포트(기본 0 = 빈 포트 자동 선택)")
    p.add_argument("--run-root", dest="run_root", help="실행 폴더 위치(기본 artifacts/runs)")
    p.add_argument("--shot-inverted", dest="shot_inverted", type=int, choices=(0, 1),
                   help="'Shoot by default' 설정 값. 지정하면 결과의 config에 기록한다(셸 지원 시 적용)")
    return p


def _load_params(raw: str) -> dict:
    text = raw
    candidate = Path(raw)
    if not raw.lstrip().startswith("{") and candidate.is_file():
        text = candidate.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise ArgError(f"--policy-params가 JSON이 아닙니다: {exc}") from exc
    if not isinstance(value, dict):
        raise ArgError("--policy-params는 JSON 객체여야 합니다")
    return value


def parse_args(argv: list[str]) -> RunConfig:
    """명령줄과 설정 파일을 합쳐 검증한다. 문제가 있으면 ArgError."""
    parser = build_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:  # argparse 오류는 종료 코드 2로 통일한다.
        if exc.code in (0, None):
            raise
        raise ArgError("명령줄 인자가 올바르지 않습니다(위 오류 메시지 참고)") from None

    values: dict = {}
    if ns.config:
        path = Path(ns.config)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ArgError(f"설정 파일을 읽을 수 없습니다: {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ArgError("설정 파일은 JSON 객체여야 합니다")
        known = set(RunConfig.__dataclass_fields__)
        unknown = sorted(set(loaded) - known)
        if unknown:
            raise ArgError(f"설정 파일에 알 수 없는 키가 있습니다: {', '.join(unknown)}")
        values.update(loaded)
    for key in RunConfig.__dataclass_fields__:
        cli_value = getattr(ns, key, None)
        if cli_value is not None:
            values[key] = cli_value

    if isinstance(values.get("policy_params"), str):
        values["policy_params"] = _load_params(values["policy_params"])
    cfg = RunConfig(**values)
    _validate(cfg)
    return cfg


def _validate(cfg: RunConfig) -> None:
    for name in ("experiment_id", "policy"):
        value = getattr(cfg, name)
        if not _ID_PATTERN.match(value):
            raise ArgError(f"{name} 값이 올바르지 않습니다(영문·숫자·._- , 최대 64자): {value!r}")
    if cfg.mode not in MODES:
        raise ArgError(f"mode는 {MODES} 중 하나여야 합니다: {cfg.mode!r}")
    if cfg.difficulty not in DIFFICULTIES:
        raise ArgError(f"difficulty는 {DIFFICULTIES} 중 하나여야 합니다: {cfg.difficulty!r}")
    if cfg.shotmode and cfg.shotmode not in SHOTMODES:
        raise ArgError(f"shotmode는 {SHOTMODES} 중 하나여야 합니다: {cfg.shotmode!r}")
    if cfg.build_flavor not in ("release", "developer"):
        raise ArgError(f"build_flavor는 release 또는 developer여야 합니다: {cfg.build_flavor!r}")
    if cfg.stage and cfg.spell:
        raise ArgError("--stage와 --spell은 함께 쓸 수 없습니다")
    if cfg.seed is not None:
        raise ArgError("--seed는 아직 지원하지 않습니다(게임에 시드 지정 경로가 없음, 세션 2 fork 변경 이후 활성화)")
    for key in _INT_KEYS:
        value = getattr(cfg, key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ArgError(f"{key}는 정수여야 합니다: {value!r}")
    for key in _FLOAT_KEYS:
        value = getattr(cfg, key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ArgError(f"{key}는 숫자여야 합니다: {value!r}")
    if cfg.max_frames < 1:
        raise ArgError("max_frames는 1 이상이어야 합니다")
    if cfg.episodes < 1 or cfg.episodes > 1000:
        raise ArgError("episodes는 1~1000이어야 합니다")
    if cfg.wall_timeout_s <= 0 or cfg.startup_timeout_s <= 0 or cfg.smoke_duration_s < 0:
        raise ArgError("시간 한도는 0보다 커야 합니다(smoke_duration_s는 0 이상)")
    if not 0 <= cfg.port <= 65535:
        raise ArgError("port는 0~65535여야 합니다")
    if cfg.shot_inverted not in (None, 0, 1):
        raise ArgError("shot_inverted는 0 또는 1이어야 합니다")
    if cfg.mode == "smoke" and (cfg.stage or cfg.spell):
        raise ArgError("smoke 모드는 스테이지·스펠을 지정할 수 없습니다")
