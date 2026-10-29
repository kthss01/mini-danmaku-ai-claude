"""표준 라이브러리만 쓰는 최소 Chrome DevTools Protocol 클라이언트.

설치할 외부 패키지 없이(Playwright·websockets 불필요) 한 페이지를 제어하기 위한 것이다.
지원 범위: 텍스트 프레임 송수신, ping/pong, close, 조각(continuation) 프레임.
이 실행기가 쓰는 CDP 메서드(Page/Runtime/Log/Input)만 다루며 범용 클라이언트가 아니다.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import socket
import struct
import threading
import time
import urllib.parse
from typing import Any


class CdpError(Exception):
    """CDP 연결·호출 오류."""


class CdpTimeout(CdpError):
    """CDP 응답 대기 시간 초과."""


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise CdpError("연결이 닫혔습니다")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def encode_frame(opcode: int, payload: bytes, mask: bool = True) -> bytes:
    """WebSocket 프레임(FIN=1) 하나를 만든다. 클라이언트 프레임은 반드시 마스킹한다."""
    header = bytearray([0x80 | opcode])
    length = len(payload)
    mask_bit = 0x80 if mask else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length < (1 << 16):
        header.append(mask_bit | 126)
        header += struct.pack(">H", length)
    else:
        header.append(mask_bit | 127)
        header += struct.pack(">Q", length)
    if mask:
        key = os.urandom(4)
        header += key
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return bytes(header) + payload


def read_frame(sock: socket.socket) -> tuple[bool, int, bytes]:
    """프레임 하나를 읽어 (fin, opcode, payload)를 돌려준다."""
    first, second = _recv_exact(sock, 2)
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        (length,) = struct.unpack(">H", _recv_exact(sock, 2))
    elif length == 127:
        (length,) = struct.unpack(">Q", _recv_exact(sock, 8))
    key = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length) if length else b""
    if masked:
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return fin, opcode, payload


class CdpConnection:
    """페이지 하나에 대한 CDP WebSocket 연결. 읽기 스레드가 응답과 이벤트를 분배한다."""

    def __init__(self, ws_url: str, connect_timeout: float = 10.0):
        parts = urllib.parse.urlsplit(ws_url)
        if parts.scheme != "ws" or parts.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise CdpError(f"로컬 ws:// 주소만 허용합니다: {ws_url}")
        self._sock = socket.create_connection((parts.hostname, parts.port), timeout=connect_timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise CdpError("WebSocket 핸드셰이크 중 연결이 닫혔습니다")
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise CdpError(f"WebSocket 핸드셰이크 실패: {response[:120]!r}")
        self._sock.settimeout(None)
        self._send_lock = threading.Lock()
        self._next_id = 0
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self.events: queue.Queue = queue.Queue()
        self.closed = threading.Event()
        self.close_reason = ""
        self._reader = threading.Thread(target=self._read_loop, name="cdp-reader", daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        message = bytearray()
        try:
            while True:
                fin, opcode, payload = read_frame(self._sock)
                if opcode == 0x9:  # ping
                    with self._send_lock:
                        self._sock.sendall(encode_frame(0xA, payload))
                    continue
                if opcode == 0xA:  # pong
                    continue
                if opcode == 0x8:  # close
                    self.close_reason = "서버가 연결을 닫았습니다"
                    break
                if opcode in (0x1, 0x2, 0x0):
                    message += payload
                    if fin:
                        self._dispatch(json.loads(message.decode("utf-8")))
                        message = bytearray()
        except (OSError, CdpError, ValueError) as exc:
            if not self.close_reason:
                self.close_reason = f"연결 오류: {exc}"
        finally:
            self.closed.set()
            with self._pending_lock:
                waiting = list(self._pending.values())
            for slot in waiting:
                slot.put({"error": {"message": self.close_reason or "연결이 닫혔습니다"}})

    def _dispatch(self, data: dict) -> None:
        if "id" in data:
            with self._pending_lock:
                slot = self._pending.pop(data["id"], None)
            if slot is not None:
                slot.put(data)
        else:
            self.events.put(data)

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> Any:
        """CDP 메서드를 호출하고 result를 돌려준다. 오류 응답은 CdpError로 올린다."""
        if self.closed.is_set():
            raise CdpError(self.close_reason or "연결이 닫혔습니다")
        with self._pending_lock:
            self._next_id += 1
            call_id = self._next_id
            slot: queue.Queue = queue.Queue(maxsize=1)
            self._pending[call_id] = slot
        body = json.dumps({"id": call_id, "method": method, "params": params or {}}).encode()
        try:
            with self._send_lock:
                self._sock.sendall(encode_frame(0x1, body))
        except OSError as exc:
            raise CdpError(f"전송 실패: {exc}") from exc
        try:
            data = slot.get(timeout=timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(call_id, None)
            raise CdpTimeout(f"{method} 응답이 {timeout}초 안에 오지 않았습니다") from None
        if "error" in data:
            raise CdpError(f"{method}: {data['error'].get('message', data['error'])}")
        return data.get("result", {})

    def evaluate(self, expression: str, timeout: float = 30.0, await_promise: bool = False) -> Any:
        """페이지에서 식을 평가하고 JSON 직렬화 가능한 값을 돌려준다. 예외는 CdpError로 올린다."""
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
            timeout=timeout,
        )
        if "exceptionDetails" in result:
            detail = result["exceptionDetails"]
            text = (detail.get("exception") or {}).get("description") or detail.get("text", "")
            raise CdpError(f"페이지 평가 예외: {text}")
        return result.get("result", {}).get("value")

    def drain_events(self) -> list[dict]:
        items = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return items

    def close(self) -> None:
        try:
            with self._send_lock:
                self._sock.sendall(encode_frame(0x8, b""))
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass
        self.closed.set()
        self._reader.join(timeout=2.0)


def wait_until(predicate, timeout: float, interval: float = 0.25):
    """predicate가 참 값을 돌려줄 때까지 기다린다. 시간 초과 시 None."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)
