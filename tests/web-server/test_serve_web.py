"""scripts/serve-web.py 동작 검증(fixture 기준).

실행:
    python -m unittest discover -s tests/web-server -t tests/web-server -v
"""

from __future__ import annotations

import contextlib
import http.client
import io
import os
import re
import socket
import subprocess
import sys
import tempfile
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
