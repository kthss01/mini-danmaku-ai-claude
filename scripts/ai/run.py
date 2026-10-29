"""AI 실험 실행기 진입점. 자세한 계약은 docs/ai/RUNNER.md.

사용 예:
    python scripts/ai/run.py --mode smoke --smoke-duration-s 10
    python scripts/ai/run.py --experiment-id spell-s1-easy --build-flavor developer --spell <id> --episodes 3
"""

from __future__ import annotations

import sys
from pathlib import Path

# 이 파일이 있는 scripts/ai만 import 경로에 둔다(현재 디렉터리의 모듈을 import하지 않는다).
sys.path.insert(0, str(Path(__file__).resolve().parent))

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and not _stream.isatty() and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import signal  # noqa: E402

from runner.orchestrator import run  # noqa: E402


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


# Windows의 Ctrl+Break(다른 프로세스 그룹에서 보낼 수 있는 유일한 신호)와 SIGTERM도 Ctrl+C처럼 정리 경로를 탄다.
for _name in ("SIGBREAK", "SIGTERM"):
    if hasattr(signal, _name):
        signal.signal(getattr(signal, _name), _raise_interrupt)


if __name__ == "__main__":
    try:
        sys.exit(run(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
