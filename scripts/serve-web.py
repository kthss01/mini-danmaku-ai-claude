"""Taisei 웹 산출물을 로컬 HTTP로 제공한다.

사용 예:
    python scripts/serve-web.py
    python scripts/serve-web.py --root build/web/site --port 8080
    python scripts/serve-web.py --root build/taisei-web --index taisei.html
    python scripts/serve-web.py --port 0            # 비어 있는 포트를 자동 선택

동작:
- 기본 루트는 세션 1 산출물 계약(build/web/site)이며 --root 로 바꿀 수 있다.
- 기본으로 127.0.0.1 에만 바인딩하여 LAN 에 노출하지 않는다. --host 로 변경 가능.
- .wasm 은 application/wasm 으로, .js 는 text/javascript 로 제공한다
  (WebAssembly.instantiateStreaming 이 정확한 MIME 을 요구한다).
- 빌드를 갱신한 뒤 오래된 파일이 쓰이지 않도록 Cache-Control: no-store 를 보낸다.
- 디렉터리 목록은 노출하지 않는다. 디렉터리 요청은 index 파일이 있을 때만 성공한다.
- 현재 Taisei 웹 빌드는 pthreads 를 쓰지 않으므로 COOP/COEP 격리 헤더를 기본으로 보내지 않는다.
  스레드 빌드가 필요해지면 --cross-origin-isolation 으로 켠다.
- 종료는 Ctrl+C 다.

종료 코드:
    0  정상 종료(Ctrl+C 포함)
    2  루트 디렉터리 또는 index 파일이 없음
    3  포트가 이미 사용 중이거나 바인딩 실패
"""

from __future__ import annotations

import argparse
import errno
import functools
import http.server
import os
import posixpath
import socket
import sys
import urllib.parse
from pathlib import Path

# 파이프로 출력할 때(도구·파일 리다이렉트) 한글이 깨지지 않도록 UTF-8 로 맞춘다. 콘솔 직접 출력은 OS 가 처리한다.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and not _stream.isatty() and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "build" / "web" / "site"
DEFAULT_INDEX = "index.html"

EXIT_OK = 0
EXIT_MISSING_ROOT = 2
EXIT_BIND_FAILED = 3

# Windows 소켓의 "주소 사용 중" 오류 코드. errno.EADDRINUSE(98/10048) 와 함께 검사한다.
_WSAEADDRINUSE = 10048
_WSAEACCES = 10013

# 확장자별 MIME 형식. OS 레지스트리(mimetypes 기본값)에 좌우되지 않도록 고정한다.
MIME_TYPES = {
    ".wasm": "application/wasm",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".txt": "text/plain",
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".data": "application/octet-stream",
    # 확장자 없는 파일(해시 이름의 리소스 등)은 octet-stream 으로 제공한다.
    "": "application/octet-stream",
}


class WebAssetsHandler(http.server.SimpleHTTPRequestHandler):
    """정적 파일 전용 핸들러. MIME 고정, 캐시 비활성화, 디렉터리 목록 차단."""

    # 서버 식별 문자열에 Python 버전을 노출하지 않는다.
    server_version = "taisei-serve-web/1"
    sys_version = ""

    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **MIME_TYPES}

    # 생성자에서 directory/index/isolation 을 주입한다(functools.partial 사용).
    def __init__(self, *args, index_name: str = DEFAULT_INDEX, cross_origin_isolation: bool = False,
                 quiet: bool = False, **kwargs):
        self.index_name = index_name
        self.cross_origin_isolation = cross_origin_isolation
        self.quiet = quiet
        # 심볼릭 링크·정션을 따라간 최종 경로가 이 안에 있어야만 제공한다.
        self.root_resolved = Path(kwargs.get("directory") or os.getcwd()).resolve()
        # BaseHTTPRequestHandler.__init__ 은 요청 처리까지 수행하므로 위 속성을 먼저 둔다.
        super().__init__(*args, **kwargs)

    def is_inside_root(self, path: str) -> bool:
        """경로를 resolve 한 결과가 루트 안인지 확인한다(symlink/junction 로 루트 밖을 가리키면 거부)."""
        try:
            real = Path(path).resolve()
        except (OSError, RuntimeError):
            return False
        return real == self.root_resolved or self.root_resolved in real.parents

    def send_head(self):
        # 디렉터리 요청은 index 파일이 있을 때만 제공한다. 목록 출력은 하지 않는다.
        path = self.translate_path(self.path)
        if getattr(self, "path_rejected", False) or not self.is_inside_root(path):
            self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
            return None
        if Path(path).is_dir():
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.endswith("/"):
                # 표준 핸들러와 같이 슬래시 없는 디렉터리는 301 로 안내한다.
                self.send_response(http.HTTPStatus.MOVED_PERMANENTLY)
                new_parts = (parts[0], parts[1], parts[2] + "/", parts[3], parts[4])
                self.send_header("Location", urllib.parse.urlunsplit(new_parts))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            index = Path(path) / self.index_name
            if not index.is_file() or not self.is_inside_root(str(index)):
                self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
                return None
            # 표준 핸들러는 index.html/index.htm 만 알므로 설정된 index 파일로 경로를 바꿔 준다.
            self.path = urllib.parse.urlunsplit(
                (parts[0], parts[1], parts[2] + urllib.parse.quote(self.index_name), parts[3], parts[4])
            )
        return super().send_head()

    def list_directory(self, path):  # pragma: no cover - send_head 에서 먼저 차단된다.
        self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
        return None

    def translate_path(self, path):
        # 표준 구현과 동일하되 index 파일 이름을 설정값으로 바꾼다.
        # (SimpleHTTPRequestHandler 는 index.html/index.htm 만 안다.)
        path = path.split("?", 1)[0].split("#", 1)[0]
        trailing_slash = path.rstrip().endswith("/")
        try:
            path = urllib.parse.unquote(path, errors="surrogatepass")
        except UnicodeDecodeError:
            path = urllib.parse.unquote(path)
        path = posixpath.normpath(path)
        words = [w for w in path.split("/") if w]
        result = Path(self.directory)
        # 거부한 요소가 하나라도 있으면 send_head 가 404 를 보낸다(표준 핸들러처럼 조용히 버리고 루트를 주지 않는다).
        self.path_rejected = False
        for word in words:
            # 드라이브·상위 디렉터리·OS 구분자(Windows 의 '\')가 든 요소는 루트 밖으로 나갈 수 있으므로 거부한다.
            if os.path.dirname(word) or word in (os.curdir, os.pardir, ".", ".."):
                self.path_rejected = True
                continue
            drive, _ = os.path.splitdrive(word)
            if drive or ":" in word or "\\" in word or Path(word).is_absolute():
                self.path_rejected = True
                continue
            result = result / word
        if trailing_slash:
            result = result / ""
        return str(result)

    def guess_type(self, path):
        _, ext = posixpath.splitext(str(path))
        ext = ext.lower()
        if ext in MIME_TYPES:
            return MIME_TYPES[ext]
        return super().guess_type(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        # 브라우저가 Content-Type 을 추측하지 않도록 한다(MIME 오류가 조용히 숨지 않게 함).
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.cross_origin_isolation:
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()

    def log_message(self, format, *args):
        if self.quiet:
            return
        super().log_message(format, *args)


class WebAssetsServer(http.server.ThreadingHTTPServer):
    """이미 사용 중인 포트에서는 반드시 bind 가 실패하도록 한 서버.

    표준 HTTPServer 는 SO_REUSEADDR 를 켠다. Windows 에서는 먼저 LISTEN 중인 소켓도 SO_REUSEADDR 를
    켰다면(python -m http.server 등) 두 번째 bind 가 성공해 같은 포트에 두 서버가 함께 LISTEN 하고,
    요청은 먼저 뜬 서버로 간다(세션 5 QA-05, 2026-10-23 실측). Windows 에서는 SO_REUSEADDR 를 끄고
    SO_EXCLUSIVEADDRUSE 로 bind 해서, 상대가 어떤 옵션을 썼든 WSAEADDRINUSE/WSAEACCES 로 실패하게 한다.
    Linux 는 SO_REUSEADDR 가 LISTEN 중인 포트의 중복 bind 를 허용하지 않으므로 표준 동작을 유지한다.
    """

    daemon_threads = True
    exclusive_bind = os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE")
    if exclusive_bind:
        allow_reuse_address = False

    def server_bind(self):
        if self.exclusive_bind:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_server(root: Path, host: str = "127.0.0.1", port: int = 8080, index_name: str = DEFAULT_INDEX,
                  cross_origin_isolation: bool = False, quiet: bool = False) -> WebAssetsServer:
    """바인딩까지 끝난 서버 객체를 돌려준다. 루트 검증은 호출자가 한다."""
    handler = functools.partial(
        WebAssetsHandler,
        directory=str(root),
        index_name=index_name,
        cross_origin_isolation=cross_origin_isolation,
        quiet=quiet,
    )
    return WebAssetsServer((host, port), handler)


def validate_root(root: Path, index_name: str) -> str | None:
    """루트·index 검증. 문제가 있으면 오류 메시지를, 없으면 None 을 돌려준다."""
    if not root.is_dir():
        return (
            f"serve-web: 루트 디렉터리가 없습니다: {root}\n"
            "  먼저 웹 빌드를 생성하거나 --root 로 산출물 디렉터리를 지정하세요."
        )
    if not (root / index_name).is_file():
        return (
            f"serve-web: {index_name} 이(가) {root} 안에 없습니다.\n"
            "  산출물이 완전한지 확인하거나 --index 로 진입 파일 이름을 지정하세요(예: --index taisei.html)."
        )
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Taisei 웹 산출물을 로컬 HTTP 로 제공한다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="종료는 Ctrl+C. 종료 코드: 0 정상, 2 루트/index 없음, 3 포트 바인딩 실패.",
    )
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help=f"제공할 디렉터리 (기본: {DEFAULT_ROOT.relative_to(REPO_ROOT).as_posix()})")
    parser.add_argument("--host", default="127.0.0.1", help="바인딩 주소 (기본: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="포트 (기본: 8080, 0 이면 자동 선택)")
    parser.add_argument("--index", default=DEFAULT_INDEX, help=f"디렉터리 진입 파일 (기본: {DEFAULT_INDEX})")
    parser.add_argument("--cross-origin-isolation", action="store_true",
                        help="COOP/COEP 헤더를 보낸다. pthreads(SharedArrayBuffer) 빌드에만 필요")
    parser.add_argument("--quiet", action="store_true", help="요청 로그를 출력하지 않는다")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()

    problem = validate_root(root, args.index)
    if problem:
        print(problem, file=sys.stderr)
        return EXIT_MISSING_ROOT

    try:
        server = create_server(
            root,
            host=args.host,
            port=args.port,
            index_name=args.index,
            cross_origin_isolation=args.cross_origin_isolation,
            quiet=args.quiet,
        )
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, _WSAEADDRINUSE, _WSAEACCES, errno.EACCES):
            print(
                f"serve-web: {args.host}:{args.port} 포트를 열 수 없습니다(이미 사용 중이거나 권한 없음): {exc}\n"
                "  다른 포트를 --port 로 지정하거나 --port 0 으로 자동 선택하세요.",
                file=sys.stderr,
            )
        else:
            print(f"serve-web: 바인딩 실패 {args.host}:{args.port}: {exc}", file=sys.stderr)
        return EXIT_BIND_FAILED

    host, port = server.server_address[:2]
    url_host = host if ":" not in host else f"[{host}]"
    print(f"serve-web: 루트 {root}")
    print(f"serve-web: 격리 헤더(COOP/COEP) {'켜짐' if args.cross_origin_isolation else '꺼짐'}")
    print(f"serve-web: http://{url_host}:{port}/ 에서 제공 중 (종료: Ctrl+C)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nserve-web: 종료합니다.")
    finally:
        server.server_close()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
