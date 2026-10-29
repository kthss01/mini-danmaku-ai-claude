"""scripts/serve-web.py를 빈 포트로 띄우고 정리한다."""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import procs

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVE_WEB = REPO_ROOT / "scripts" / "serve-web.py"
_URL_PATTERN = re.compile(r"http://[^\s:]+:(\d+)/")


class ServerError(Exception):
    """서버를 띄우지 못함."""


class SiteServer:
    def __init__(self, root: Path, log_path: Path, port: int = 0):
        self.root = root
        self.log_path = log_path
        self.requested_port = port
        self.process: subprocess.Popen | None = None
        self.port: int | None = None
        self._log_file = None
        self._reader: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self, timeout: float = 20.0) -> None:
        self._log_file = open(self.log_path, "a", encoding="utf-8")
        # -u: 출력 버퍼링을 끄고, -I: 현재 디렉터리의 모듈을 import하지 않는다.
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-I", str(SERVE_WEB), "--root", str(self.root),
             "--port", str(self.requested_port)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", **procs.popen_flags(),
        )
        self._reader = threading.Thread(target=self._pump, name="server-log", daemon=True)
        self._reader.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self._reader.join(timeout=2)
                raise ServerError(f"서버가 바로 종료됐습니다(종료 코드 {self.process.returncode}), 로그: {self.log_path}")
            if self._ready.wait(0.1):
                return
        raise ServerError("서버 시작 시간 초과")

    def _pump(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            self._log_file.write(line)
            self._log_file.flush()
            if self.port is None:
                match = _URL_PATTERN.search(line)
                if match:
                    self.port = int(match.group(1))
                    self._ready.set()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def stop(self) -> dict:
        """서버를 종료하고 포트가 닫혔는지 확인한다."""
        info = {"pid": self.process.pid if self.process else None, "port": self.port,
                "port_closed": True, "process_gone": True}
        if self.process is not None and self.process.poll() is None:
            procs.kill_tree(self.process.pid)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if self._reader is not None:
            self._reader.join(timeout=2)
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
        if self.process is not None:
            info["process_gone"] = not procs.pid_alive(self.process.pid)
        if self.port is not None:
            info["port_closed"] = procs.wait_port_closed(self.port)
        return info
