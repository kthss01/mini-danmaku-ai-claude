"""자기가 만든 프로세스만 찾아 정리하는 도구.

다른 세션·사용자가 띄운 브라우저와 서버는 건드리지 않는다. 식별은 실행마다 새로 만든
임시 프로필 경로(--user-data-dir)가 명령줄에 들어 있는지로만 한다.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time

IS_WINDOWS = os.name == "nt"


def popen_flags() -> dict:
    """자식을 새 프로세스 그룹/세션으로 띄워 Ctrl+C가 실행기와 함께 자식에게 퍼지지 않게 한다."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def pid_alive(pid: int) -> bool:
    if IS_WINDOWS:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace",
        ).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_tree(pid: int) -> None:
    """pid와 그 자손을 강제 종료한다. 이미 없으면 조용히 끝난다."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def find_pids_by_cmdline(marker: str) -> list[int]:
    """명령줄에 marker 문자열이 든 프로세스 PID 목록. 이 실행기 자신은 제외한다."""
    own = os.getpid()
    pids: list[int] = []
    if IS_WINDOWS:
        # marker를 명령줄이 아닌 환경 변수로 넘긴다. 조회하는 PowerShell 자신이 결과에 잡히지 않게 하기 위해서다.
        script = (
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
            "$_.CommandLine.Contains($env:TAISEI_AI_MARKER) } | ForEach-Object { $_.ProcessId }"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, errors="replace", timeout=60,
            env={**os.environ, "TAISEI_AI_MARKER": marker},
        ).stdout
        for token in out.split():
            if token.isdigit():
                pids.append(int(token))
    else:
        out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, errors="replace").stdout
        for line in out.splitlines():
            head, _, rest = line.strip().partition(" ")
            if head.isdigit() and marker in rest:
                pids.append(int(head))
    return [p for p in pids if p != own]


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """host:port에 연결되면 True. 서버 종료 뒤 포트가 닫혔는지 확인하는 데 쓴다."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port_closed(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_open(port):
            return True
        time.sleep(0.1)
    return not port_open(port)
