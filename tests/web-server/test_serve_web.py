"""scripts/serve-web.py 동작 검증(fixture 기준).

실행:
    python -m unittest discover -s tests/web-server -t tests/web-server -v
"""

from __future__ import annotations

import contextlib
import functools
import http.client
import http.server
import io
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from _support import FIXTURE_SITE, LiveServer, SCRIPTS_DIR, serve_web


class ServeWebResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.live = LiveServer(FIXTURE_SITE)
        cls.live.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.live.__exit__(None, None, None)

    def test_root_serves_index_html(self):
        status, headers, body = self.live.get("/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("text/html"))
        self.assertEqual(body, (FIXTURE_SITE / "index.html").read_bytes())

    def test_wasm_mime_type(self):
        status, headers, body = self.live.get("/game/game.wasm")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/wasm")
        self.assertEqual(body, (FIXTURE_SITE / "game" / "game.wasm").read_bytes())
        self.assertEqual(int(headers["content-length"]), len(body))

    def test_javascript_mime_type(self):
        status, headers, _ = self.live.get("/game/game.js")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"].split(";")[0], "text/javascript")

    def test_nested_relative_resources(self):
        # game.html 이 참조하는 ../img/bg.png 와 data/<sha256> 가 상대 경로로 제공된다.
        status, headers, _ = self.live.get("/img/bg.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "image/png")
        data_file = next((FIXTURE_SITE / "game" / "data").iterdir())
        status, headers, body = self.live.get(f"/game/data/{data_file.name}")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/octet-stream")
        self.assertEqual(body, data_file.read_bytes())

    def test_missing_file_is_404(self):
        status, _, _ = self.live.get("/game/missing.wasm")
        self.assertEqual(status, 404)
        status, _, _ = self.live.get("/nope.html")
        self.assertEqual(status, 404)

    def test_cache_and_sniff_headers(self):
        _, headers, _ = self.live.get("/game/game.wasm")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["x-content-type-options"], "nosniff")

    def test_no_isolation_headers_by_default(self):
        _, headers, _ = self.live.get("/game/game.html")
        self.assertNotIn("cross-origin-opener-policy", headers)
        self.assertNotIn("cross-origin-embedder-policy", headers)

    def test_directory_listing_not_exposed(self):
        # data/ 에는 index.html 이 없으므로 목록 대신 404 여야 한다.
        status, _, body = self.live.get("/game/data/")
        self.assertEqual(status, 404)
        self.assertNotIn(b"Directory listing", body)

    def test_directory_without_slash_redirects(self):
        # urllib 은 301 을 자동으로 따라가므로 http.client 로 원 응답을 직접 본다.
        host, port = self.live.server.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=10)
        try:
            conn.request("GET", "/game")
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 301)
            self.assertTrue(response.getheader("Location", "").endswith("/game/"))
        finally:
            conn.close()

    def test_head_request(self):
        status, headers, body = self.live.get("/game/game.wasm", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/wasm")
        self.assertEqual(body, b"")

    def test_query_string_ignored(self):
        status, headers, _ = self.live.get("/game/game.js?v=123")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"].split(";")[0], "text/javascript")


class ServeWebOptionTests(unittest.TestCase):
    def test_isolation_headers_when_enabled(self):
        with LiveServer(FIXTURE_SITE, cross_origin_isolation=True) as live:
            _, headers, _ = live.get("/game/game.html")
            self.assertEqual(headers["cross-origin-opener-policy"], "same-origin")
            self.assertEqual(headers["cross-origin-embedder-policy"], "require-corp")

    def test_custom_index_name(self):
        # --index game.html 처럼 index.html 이 아닌 진입 파일도 디렉터리 요청으로 제공된다.
        with LiveServer(FIXTURE_SITE / "game", index_name="game.html") as live:
            status, headers, body = live.get("/")
            self.assertEqual(status, 200)
            self.assertTrue(headers["content-type"].startswith("text/html"))
            self.assertEqual(body, (FIXTURE_SITE / "game" / "game.html").read_bytes())

    def test_path_traversal_stays_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "secret.txt"
            outside.write_text("secret", encoding="utf-8")
            root = Path(tmp) / "site"
            root.mkdir()
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            with LiveServer(root) as live:
                for path in (
                    "/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "/site/../../secret.txt",
                    # Windows 구분자: unquote 하면 '..\\secret.txt' 한 요소가 된다.
                    "/..%5csecret.txt", "/%5c..%5csecret.txt", "/game/..%5c..%5csecret.txt",
                    "/..%5c..%5c..%5csecret.txt", "/%2e%2e%5c%2e%2e%5csecret.txt",
                ):
                    status, _, body = live.get(path)
                    self.assertNotEqual(body, b"secret", path)
                    # 거부된 요소를 조용히 버리고 루트 index 를 주지도 않는다.
                    self.assertEqual(status, 404, path)

    def test_symlink_outside_root_is_refused(self):
        # 루트 안의 symlink/정션이 루트 밖을 가리키면 404. 심볼릭 링크 권한이 없는 환경은 건너뛴다.
        with tempfile.TemporaryDirectory() as tmp:
            outside_file = Path(tmp) / "secret.txt"
            outside_file.write_text("secret", encoding="utf-8")
            outside_dir = Path(tmp) / "outside"
            outside_dir.mkdir()
            (outside_dir / "index.html").write_text("outside index", encoding="utf-8")
            (outside_dir / "leak.txt").write_text("leak", encoding="utf-8")
            root = Path(tmp) / "site"
            root.mkdir()
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            (root / "inside.txt").write_text("inside", encoding="utf-8")
            try:
                os.symlink(outside_file, root / "link.txt")
                os.symlink(outside_dir, root / "linkdir", target_is_directory=True)
                os.symlink(root / "inside.txt", root / "inside-link.txt")
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink 을 만들 수 없는 환경: {exc}")
            with LiveServer(root) as live:
                status, _, body = live.get("/link.txt")
                self.assertEqual(status, 404)
                self.assertNotEqual(body, b"secret")
                status, _, body = live.get("/linkdir/")
                self.assertEqual(status, 404)
                self.assertNotIn(b"outside index", body)
                status, _, body = live.get("/linkdir/leak.txt")
                self.assertEqual(status, 404)
                self.assertNotEqual(body, b"leak")
                # 루트 안을 가리키는 링크는 정상 제공된다.
                status, _, body = live.get("/inside-link.txt")
                self.assertEqual(status, 200)
                self.assertEqual(body, b"inside")


class ServeWebMainTests(unittest.TestCase):
    def run_main(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = serve_web.main(argv)
        return code, err.getvalue()

    def test_missing_root_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err = self.run_main(["--root", str(Path(tmp) / "nope"), "--port", "0"])
        self.assertEqual(code, serve_web.EXIT_MISSING_ROOT)
        self.assertIn("루트 디렉터리가 없습니다", err)

    def test_missing_index_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err = self.run_main(["--root", tmp, "--port", "0"])
        self.assertEqual(code, serve_web.EXIT_MISSING_ROOT)
        self.assertIn("index.html", err)
        self.assertIn("--index", err)

    def test_port_in_use_exits_3(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]
        try:
            code, err = self.run_main(["--root", str(FIXTURE_SITE), "--port", str(port)])
        finally:
            blocker.close()
        self.assertEqual(code, serve_web.EXIT_BIND_FAILED)
        self.assertIn("--port", err)

    def assert_bind_refused(self, port: int, **kwargs) -> None:
        """같은 포트에 우리 서버 bind 가 OSError 로 거부되는지 확인한다.

        main() 을 직접 부르면 회귀로 bind 가 성공할 때 serve_forever 에서 영원히 멈추므로(2026-10-23 실제로 3시간 정지),
        프로세스 내 테스트는 create_server 의 예외만 확인한다. 종료 코드 3 은 시간 제한이 있는 프로세스 테스트가 확인한다.
        """
        try:
            server = serve_web.create_server(FIXTURE_SITE, port=port, quiet=True, **kwargs)
        except OSError:
            return
        server.server_close()
        self.fail(f"127.0.0.1:{port} 가 이미 LISTEN 중인데 bind 가 성공했습니다(중복 LISTEN)")

    def test_port_held_by_stdlib_http_server_is_refused_and_kept(self):
        # python -m http.server 와 같은 표준 서버(SO_REUSEADDR 켬)가 점유한 포트. Windows 에서 중복 LISTEN 되던 경우.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("A-server", encoding="utf-8")

            class QuietHandler(http.server.SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass

            other = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=tmp))
            self.assertTrue(other.allow_reuse_address)
            thread = threading.Thread(target=other.serve_forever, daemon=True)
            thread.start()
            port = other.server_address[1]
            try:
                self.assert_bind_refused(port)
                # 기존 서버는 그대로 응답한다.
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as response:
                    self.assertEqual(response.read(), b"A-server")
            finally:
                other.shutdown()
                other.server_close()

    def test_port_held_by_own_server_is_refused_and_kept(self):
        with LiveServer(FIXTURE_SITE) as live:
            port = live.server.server_address[1]
            self.assert_bind_refused(port)
            status, _, body = live.get("/")
            self.assertEqual(status, 200)
            self.assertEqual(body, (FIXTURE_SITE / "index.html").read_bytes())

    def test_port_zero_released_after_close(self):
        # --port 0 으로 뜬 서버가 요청을 처리하고 닫힌 뒤, 같은 포트를 바로 다시 열 수 있어야 한다.
        with LiveServer(FIXTURE_SITE) as live:
            port = live.server.server_address[1]
            for _ in range(5):
                status, _, _ = live.get("/game/game.wasm")
                self.assertEqual(status, 200)
        again = serve_web.create_server(FIXTURE_SITE, port=port, quiet=True)
        again.server_close()

    @unittest.skipUnless(os.name == "nt", "Windows 전용 소켓 옵션")
    def test_windows_uses_exclusive_bind(self):
        server = serve_web.create_server(FIXTURE_SITE, port=0, quiet=True)
        try:
            self.assertEqual(server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE), 1)
            self.assertEqual(server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR), 0)
        finally:
            server.server_close()


class ServeWebPortConflictProcessTests(unittest.TestCase):
    """세션 5 재현 그대로 실제 프로세스 두 개로 확인한다: python -m http.server 점유 → serve-web.py 종료 코드 3."""

    def test_cli_exits_3_when_python_http_server_holds_port(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("A-process", encoding="utf-8")
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            other = subprocess.Popen(
                [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", tmp],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
            )
            try:
                body = None
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                            body = response.read()
                        break
                    except OSError:
                        time.sleep(0.1)
                self.assertEqual(body, b"A-process", "python -m http.server 가 뜨지 않았습니다")
                ours = subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "serve-web.py"), "--root", str(FIXTURE_SITE), "--port", str(port)],
                    capture_output=True, text=True, encoding="utf-8", env=env, timeout=30,
                )
                self.assertEqual(ours.returncode, serve_web.EXIT_BIND_FAILED, ours.stdout + ours.stderr)
                self.assertNotIn("제공 중", ours.stdout)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                    self.assertEqual(response.read(), b"A-process")
            finally:
                other.terminate()
                other.wait(timeout=10)

    def test_cli_exits_3_when_own_server_holds_port(self):
        # serve-web.py 를 같은 포트로 두 번 실행: 두 번째는 종료 코드 3, 첫 번째는 계속 응답한다.
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        first = subprocess.Popen(
            [sys.executable, "-u", str(SCRIPTS_DIR / "serve-web.py"), "--root", str(FIXTURE_SITE), "--port", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env,
        )
        try:
            port = None
            for _ in range(20):
                line = first.stdout.readline()
                if not line:
                    break
                match = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
                if match:
                    port = int(match.group(1))
                    break
            self.assertIsNotNone(port, "첫 서버의 URL 안내 줄을 찾지 못했습니다")
            second = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "serve-web.py"), "--root", str(FIXTURE_SITE / "game"),
                 "--index", "game.html", "--port", str(port)],
                capture_output=True, text=True, encoding="utf-8", env=env, timeout=30,
            )
            self.assertEqual(second.returncode, serve_web.EXIT_BIND_FAILED, second.stdout + second.stderr)
            self.assertIn("포트를 열 수 없습니다", second.stderr)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                self.assertEqual(response.read(), (FIXTURE_SITE / "index.html").read_bytes())
        finally:
            first.terminate()
            first.wait(timeout=10)
            first.stdout.close()


class ServeWebCommandLineTests(unittest.TestCase):
    """문서에 적은 명령 그대로 자식 프로세스로 실행해 URL 을 안내하고 종료되는지 확인한다."""

    def test_cli_serves_and_terminates(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen(
            [sys.executable, "-u", str(SCRIPTS_DIR / "serve-web.py"), "--root", str(FIXTURE_SITE), "--port", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env,
        )
        try:
            url = None
            for _ in range(20):
                line = proc.stdout.readline()
                if not line:
                    break
                match = re.search(r"(http://127\.0\.0\.1:\d+)/", line)
                if match:
                    url = match.group(1)
                    break
            self.assertIsNotNone(url, "서버 URL 안내 줄을 찾지 못했습니다")
            with urllib.request.urlopen(url + "/game/game.wasm", timeout=10) as response:
                self.assertEqual(response.headers["Content-Type"], "application/wasm")
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
