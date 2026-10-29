"""Chrome/Edge를 임시 프로필로 띄우고 정리한다."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from . import procs
from .cdp import CdpConnection, CdpError


class BrowserError(Exception):
    """브라우저를 찾거나 띄우지 못함."""


_WINDOWS_CANDIDATES = {
    "chrome": [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ],
    "msedge": [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],
}
_POSIX_CANDIDATES = {
    "chrome": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "msedge": ["microsoft-edge", "microsoft-edge-stable"],
}


def find_browser(spec: str) -> str | None:
    """'chrome'·'msedge' 또는 실행 파일 경로를 실제 경로로 바꾼다. 없으면 None."""
    if spec not in _WINDOWS_CANDIDATES:
        return spec if Path(spec).is_file() else None
    if procs.IS_WINDOWS:
        for template in _WINDOWS_CANDIDATES[spec]:
            path = os.path.expandvars(template)
            if Path(path).is_file():
                return path
        return None
    for name in _POSIX_CANDIDATES[spec]:
        found = shutil.which(name)
        if found:
            return found
    return None


class Browser:
    """실행(에피소드)마다 새 임시 프로필로 브라우저 한 개를 띄운다.

    프로필을 매번 새로 쓰므로 IndexedDB(게임 설정·진행 저장)가 에피소드 사이에 섞이지 않는다.
    """

    def __init__(self, executable: str, headless: bool, window_size: tuple[int, int] = (1280, 800)):
        self.executable = executable
        self.headless = headless
        self.window_size = window_size
        self.profile_dir = Path(tempfile.mkdtemp(prefix="taisei-ai-profile-"))
        self.process: subprocess.Popen | None = None
        self.port: int | None = None
        self.version = ""
        self.conn: CdpConnection | None = None
        self.leaked_pids: list[int] = []

    @property
    def marker(self) -> str:
        return str(self.profile_dir)

    def _args(self) -> list[str]:
        args = [
            self.executable,
            "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-features=Translate,MediaRouter",
            "--autoplay-policy=no-user-gesture-required",
            f"--window-size={self.window_size[0]},{self.window_size[1]}",
        ]
        if self.headless:
            # 헤드리스에서 WebGL 2를 쓰려면 소프트웨어 렌더러가 필요하다.
            args += ["--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                     "--ignore-gpu-blocklist", "--hide-scrollbars", "--mute-audio"]
        args.append("about:blank")
        return args

    def launch(self, timeout: float = 30.0) -> None:
        self.process = subprocess.Popen(
            self._args(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **procs.popen_flags(),
        )
        port_file = self.profile_dir / "DevToolsActivePort"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise BrowserError(f"브라우저가 바로 종료됐습니다(종료 코드 {self.process.returncode})")
            if port_file.is_file():
                lines = port_file.read_text(encoding="utf-8", errors="replace").splitlines()
                if lines and lines[0].isdigit():
                    self.port = int(lines[0])
                    break
            time.sleep(0.1)
        if self.port is None:
            raise BrowserError("DevToolsActivePort가 나타나지 않았습니다")
        self.version = str(self._get_json("/json/version").get("Browser", ""))
        page = self._wait_page_target(deadline)
        try:
            self.conn = CdpConnection(page["webSocketDebuggerUrl"])
        except CdpError as exc:
            raise BrowserError(f"DevTools 연결 실패: {exc}") from exc

    def _get_json(self, path: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _wait_page_target(self, deadline: float) -> dict:
        while time.monotonic() < deadline:
            try:
                for target in self._get_json("/json/list"):
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        return target
            except OSError:
                pass
            time.sleep(0.1)
        raise BrowserError("페이지 대상을 찾지 못했습니다")

    def close(self) -> dict:
        """정상 종료를 먼저 시도하고, 남은 프로세스는 이 프로필로 띄운 것만 강제 종료한다.

        돌려주는 값: {"forced": 강제 종료한 PID 목록, "remaining": 정리 뒤에도 남은 PID 목록}
        """
        errors: list[str] = []
        if self.conn is not None:
            try:
                self.conn.call("Browser.close", timeout=5)
            except CdpError:
                pass
            try:
                self.conn.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"연결 종료 예외: {exc!r}")
            self.conn = None
        if self.process is not None:
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass
        forced: list[int] = []
        remaining: list[int] | None = []
        # 자손(렌더러·GPU) 프로세스가 남을 수 있으므로 프로필 경로로 한 번 더 찾는다.
        # 조회가 실패하면 남은 프로세스가 없다고 단정하지 않고 remaining=None(확인 불가)으로 남긴다.
        try:
            for attempt in range(3):
                pids = procs.find_pids_by_cmdline(self.marker)
                if not pids:
                    break
                for pid in pids:
                    if pid not in forced:
                        forced.append(pid)
                    procs.kill_tree(pid)
                time.sleep(0.5)
            remaining = procs.find_pids_by_cmdline(self.marker)
        except Exception as exc:  # noqa: BLE001
            remaining = None
            errors.append(f"프로세스 조회 실패: {exc!r}")
        # 조회 실패 때는 시작 프로세스 자체라도 강제 종료를 시도한다.
        if remaining is None and self.process is not None and self.process.poll() is None:
            procs.kill_tree(self.process.pid)
        self.leaked_pids = forced
        # 프로세스가 완전히 사라진 뒤에야 프로필이 지워진다(Windows는 열린 파일 삭제가 실패한다).
        for _ in range(10):
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            if not self.profile_dir.exists():
                break
            time.sleep(0.3)
        return {"forced": forced, "remaining": remaining, "profile_removed": not self.profile_dir.exists(),
                "errors": errors}
