"""run 폴더 생성과 결과 파일 쓰기."""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

RUN_SCHEMA = "taisei-ai-run/1"
SUMMARY_SCHEMA = "taisei-ai-run-summary/1"
# 에피소드 스키마는 세션 4(#23, PR #41)가 정한다. 실행기는 run·code·config와 실행 사실만 채운다.
EPISODE_SCHEMA = "taisei-ai-episode/1"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_run_id() -> str:
    """YYYYMMDDTHHMMSSZ-<6hex>. 같은 초에 시작해도 겹치지 않는다."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def write_json(path: Path, value) -> None:
    """임시 파일에 쓴 뒤 바꿔치기해서, 중간에 끊겨도 반쪽짜리 JSON이 남지 않게 한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class RunLogger:
    """logs/runner.log에 쓰고 표준 오류에도 알린다."""

    def __init__(self, path: Path, echo: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8")
        self._echo = echo
        self._lock = threading.Lock()

    def log(self, message: str, level: str = "INFO") -> None:
        line = f"{utc_now()} {level} {message}"
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()
            if self._echo:
                print(line, file=sys.stderr, flush=True)

    def close(self) -> None:
        self._file.close()


class RunDir:
    def __init__(self, root: Path, run_id: str):
        self.run_id = run_id
        self.path = root / run_id
        self.episodes = self.path / "episodes"
        self.logs = self.path / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.episodes.mkdir(parents=True, exist_ok=True)

    def episode_path(self, index: int) -> Path:
        return self.episodes / f"{index:04d}.json"

    def episode_extra_dir(self, index: int) -> Path:
        directory = self.episodes / f"{index:04d}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory
