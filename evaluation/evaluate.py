#!/usr/bin/env python3
"""Taisei AI 평가 도구 진입점. 사용법은 docs/ai/EVALUATION.md 참조.

    python evaluation/evaluate.py evaluate artifacts/runs/<run_id>
    python evaluation/evaluate.py compare <run>/evaluation/evaluation.json ... --out <dir>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from taisei_eval.cli import main  # noqa: E402

if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    sys.exit(main())
