"""scripts/check-web-assets.py 동작 검증(fixture 기준).

실행:
    python -m unittest discover -s tests/web-server -t tests/web-server -v
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import http.server
import io
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

import make_fixture
from _support import FIXTURE_SITE, LiveServer, check_web_assets


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """오동작 서버를 흉내 내는 테스트용 기본 핸들러(로그 없음, .wasm MIME 은 올바름)."""

    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/wasm"}

    def log_message(self, *args):
        pass


def run_check(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = check_web_assets.main(argv)
    return code, out.getvalue()


def static_report(root: Path, entry: str = "index.html", **kwargs) -> check_web_assets.Report:
    report = check_web_assets.Report(root=str(root), entry=entry, url=None)
    check_web_assets.scan_static(report, root, entry, kwargs.get("data_dir", "data"), kwargs.get("verify_hashes", False))
    return report


def codes(report: check_web_assets.Report, level: str = "error") -> list[str]:
    return [f.code for f in report.findings if f.level == level]


class FixtureConsistencyTests(unittest.TestCase):
    def test_committed_fixture_matches_generator(self):
        # 커밋된 fixture 가 생성기와 어긋나지 않았는지 확인한다.
        with tempfile.TemporaryDirectory() as tmp:
            generated = make_fixture.build_fixture(Path(tmp) / "site")
            expected = {p.relative_to(generated).as_posix(): p.read_bytes() for p in generated.rglob("*") if p.is_file()}
        actual = {p.relative_to(FIXTURE_SITE).as_posix(): p.read_bytes() for p in FIXTURE_SITE.rglob("*") if p.is_file()}
        self.assertEqual(sorted(actual), sorted(expected))
        for name, content in expected.items():
            self.assertEqual(actual[name], content, name)


class StaticScanTests(unittest.TestCase):
    def test_fixture_passes(self):
        report = static_report(FIXTURE_SITE, verify_hashes=True)
        self.assertEqual(codes(report), [])
        self.assertEqual(report.wasm_files, ["game/game.wasm"])
        self.assertFalse(report.threads_required)
        self.assertIn("game/data", report.data_dirs)
        self.assertEqual(report.data_dirs["game/data"]["files"], 2)
        self.assertEqual(report.data_dirs["game/data"]["hash_mismatch"], 0)
        # HTML/CSS/JS 경유 참조가 모두 수집된다. 주석 처리된 스크립트는 포함되지 않는다.
        self.assertEqual(report.resources, [
            "COPYING.txt", "game/game.html", "game/game.js", "game/game.wasm", "img/bg.png", "style.css",
        ])

    def test_cli_static_passes_and_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            code, text = run_check(["--root", str(FIXTURE_SITE), "--verify-hashes", "--json", str(out)])
            self.assertEqual(code, check_web_assets.EXIT_OK, text)
            payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["errors"], 0)
        self.assertIn("game/game.wasm", payload["wasm_files"])

    def test_usage_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run_check(["--root", str(Path(tmp) / "none")])
            self.assertEqual(code, check_web_assets.EXIT_USAGE)
            code, _ = run_check(["--root", tmp])
            self.assertEqual(code, check_web_assets.EXIT_USAGE)

    def mutated_fixture(self, mutate):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "site"
        shutil.copytree(FIXTURE_SITE, root)
        mutate(root)
        return root

    def test_missing_wasm_reported(self):
        root = self.mutated_fixture(lambda r: (r / "game" / "game.wasm").unlink())
        self.assertIn("missing-file", codes(static_report(root)))

    def test_case_mismatch_reported_even_on_case_insensitive_fs(self):
        def mutate(root: Path):
            html = root / "game" / "game.html"
            html.write_text(html.read_text(encoding="utf-8").replace('src="game.js"', 'src="Game.JS"'), encoding="utf-8")
        root = self.mutated_fixture(mutate)
        report = static_report(root)
        self.assertIn("case-mismatch", codes(report))
        # 깨진 참조는 추적하지 않으므로 리소스 목록에도, 열어 보는 대상에도 들어가지 않는다(Linux 에서 crash 하던 경로).
        self.assertNotIn("game/Game.JS", report.resources)
        # CLI 와 HTTP 검사까지 traceback 없이 종료 코드 1 로 끝난다.
        with LiveServer(root) as live:
            code, text = run_check(["--root", str(root), "--url", live.url])
        self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)
        self.assertNotIn("Traceback", text)

    def test_absolute_path_reported(self):
        def mutate(root: Path):
            html = root / "index.html"
            html.write_text(html.read_text(encoding="utf-8").replace('href="style.css"', 'href="/style.css"'), encoding="utf-8")
        root = self.mutated_fixture(mutate)
        self.assertIn("absolute-path", codes(static_report(root)))

    def test_escaping_root_reported(self):
        def mutate(root: Path):
            html = root / "index.html"
            html.write_text(html.read_text(encoding="utf-8").replace('href="style.css"', 'href="../style.css"'), encoding="utf-8")
        root = self.mutated_fixture(mutate)
        self.assertIn("escapes-root", codes(static_report(root)))

    def test_bad_data_name_and_hash_reported(self):
        def mutate(root: Path):
            data = root / "game" / "data"
            (data / "not-a-hash.bin").write_bytes(b"x")
            first = next(p for p in data.iterdir() if p.name != "not-a-hash.bin")
            first.write_bytes(b"corrupted")
        root = self.mutated_fixture(mutate)
        found = codes(static_report(root, verify_hashes=True))
        self.assertIn("data-name", found)
        self.assertIn("data-hash", found)
        # 해시 검증을 끄면 이름 오류만 보고된다.
        self.assertNotIn("data-hash", codes(static_report(root)))

    def test_missing_data_dir_reported(self):
        root = self.mutated_fixture(lambda r: shutil.rmtree(r / "game" / "data"))
        self.assertIn("data-dir-missing", codes(static_report(root)))

    def test_invalid_wasm_reported(self):
        root = self.mutated_fixture(lambda r: (r / "game" / "game.wasm").write_bytes(b"<html>not wasm</html>"))
        self.assertIn("wasm-invalid", codes(static_report(root)))

    def test_threaded_build_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_fixture.build_fixture(Path(tmp) / "site", shared_memory=True)
            report = static_report(root)
        self.assertTrue(report.threads_required)
        self.assertIn("wasm-shared-memory", codes(report, "info"))
        self.assertIn("threads-markers", codes(report, "info"))

    def test_entry_without_wasm_warns(self):
        root = self.mutated_fixture(lambda r: None)
        # 진입이 게임 페이지에 닿지 않는 HTML 이면 경고한다.
        (root / "lonely.html").write_text("<html><body>no game</body></html>", encoding="utf-8")
        report = static_report(root, entry="lonely.html")
        self.assertIn("no-wasm", codes(report, "warning"))


class LiveScanTests(unittest.TestCase):
    def test_fixture_against_serve_web_passes(self):
        with LiveServer(FIXTURE_SITE) as live:
            code, text = run_check(["--root", str(FIXTURE_SITE), "--url", live.url, "--sample-data", "-1", "--verify-hashes"])
        self.assertEqual(code, check_web_assets.EXIT_OK, text)
        self.assertIn("결과: 통과", text)

    def test_nested_entry_against_serve_web(self):
        # 진입을 game/game.html 로 잡아도 상대 경로(../img/bg.png, data/) 가 서버에서 풀린다.
        with LiveServer(FIXTURE_SITE) as live:
            code, text = run_check(["--root", str(FIXTURE_SITE), "--entry", "game/game.html", "--url", live.url])
        self.assertEqual(code, check_web_assets.EXIT_OK, text)

    def test_isolation_required_for_threaded_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_fixture.build_fixture(Path(tmp) / "site", shared_memory=True)
            with LiveServer(root) as live:
                code, text = run_check(["--root", str(root), "--url", live.url])
                self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)
                self.assertIn("isolation-missing", text)
            with LiveServer(root, cross_origin_isolation=True) as live:
                code, text = run_check(["--root", str(root), "--url", live.url])
                self.assertEqual(code, check_web_assets.EXIT_OK, text)
                self.assertIn("isolation-ok", text)

    def test_forced_isolation_requirement(self):
        with LiveServer(FIXTURE_SITE) as live:
            code, text = run_check(["--root", str(FIXTURE_SITE), "--url", live.url, "--require-isolation", "yes"])
            self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)
            self.assertIn("isolation-missing", text)

    def test_wrong_wasm_mime_and_html_fallback_detected(self):
        # 표준 SimpleHTTPRequestHandler 에 .wasm 을 잘못 매핑하고, 없는 경로에 200 HTML 을 돌려주는 서버를 흉내 낸다.
        class BadHandler(http.server.SimpleHTTPRequestHandler):
            extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/octet-stream"}

            def send_head(self):
                if "__check_missing_" in self.path:
                    body = b"<html>fallback</html>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    return io.BytesIO(body)
                return super().send_head()

            def log_message(self, *args):
                pass

        handler = functools.partial(BadHandler, directory=str(FIXTURE_SITE))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            code, text = run_check(["--root", str(FIXTURE_SITE), "--url", url])
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)
        self.assertIn("application/wasm", text)
        self.assertIn("not-found", text)

    def test_unreachable_server_reported(self):
        code, text = run_check(["--root", str(FIXTURE_SITE), "--url", "http://127.0.0.1:9"])
        self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)
        self.assertIn("server-unreachable", text)

    def run_against_handler(self, handler_cls, argv_extra):
        handler = functools.partial(handler_cls, directory=str(FIXTURE_SITE))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            return run_check(["--root", str(FIXTURE_SITE), "--url", url, *argv_extra])
        finally:
            server.shutdown()
            server.server_close()

    def test_entry_404_fails_even_when_other_assets_are_fine(self):
        # '/' 와 나머지 자산은 정상이지만 '/index.html' 자체만 404 인 서버.
        class EntryMissingHandler(_QuietHandler):
            def send_head(self):
                if self.path.split("?")[0] == "/index.html":
                    self.send_error(404, "File not found")
                    return None
                return super().send_head()

        code, text = self.run_against_handler(EntryMissingHandler, [])
        self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)
        self.assertIn("entry-http", text)
        self.assertIn("status 404", text)

    def test_nested_entry_404_fails(self):
        # --entry game/game.html 이 404 면 실패해야 한다.
        class GameMissingHandler(_QuietHandler):
            def send_head(self):
                if self.path.split("?")[0] == "/game/game.html":
                    self.send_error(404, "File not found")
                    return None
                return super().send_head()

        code, text = self.run_against_handler(GameMissingHandler, ["--entry", "game/game.html"])
        self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)
        self.assertIn("entry-http", text)

    def test_connection_dropped_mid_check_is_reported_not_raised(self):
        # 첫 연결 확인 뒤 .wasm 요청에서 응답 없이 연결을 끊는 서버: traceback 대신 finding 으로 끝나야 한다.
        class DropHandler(_QuietHandler):
            def handle_one_request(self):
                self.raw_requestline = self.rfile.readline(65537)
                if not self.raw_requestline:
                    self.close_connection = True
                    return
                if not self.parse_request():
                    return
                if self.path.endswith(".wasm"):
                    # 응답 없이 연결만 닫는다(서버 쪽 예외 없이).
                    self.close_connection = True
                    return
                getattr(self, "do_" + self.command)()
                self.wfile.flush()

        code, text = self.run_against_handler(DropHandler, [])
        self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)
        self.assertIn("http-error", text)
        self.assertIn("game/game.wasm", text)
        self.assertNotIn("Traceback", text)


class DynamicLoaderTests(unittest.TestCase):
    """세션 3 셸처럼 로더(game.js)를 JS 문자열로 동적 주입하는 구조를 추적하는지 검증한다."""

    def make_site(self, loader_name: str = "game.js") -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "site"
        shutil.copytree(FIXTURE_SITE, root)
        # 셸 HTML 은 game/ 에, 설정 JS 는 game/js/ 에 둔다. 로더 이름은 JS 파일이 아니라 문서 기준으로 풀려야 한다.
        (root / "game" / "js").mkdir()
        (root / "game" / "shell.html").write_text(
            '<!doctype html><html><head><meta charset="utf-8"></head><body><canvas></canvas>'
            '<script src="js/shell-config.js"></script><script src="js/shell.js"></script></body></html>',
            encoding="utf-8")
        (root / "game" / "js" / "shell-config.js").write_text(
            f"window.CFG = {{ gameBase: '', gameScript: '{loader_name}' }};\n", encoding="utf-8")
        (root / "game" / "js" / "shell.js").write_text(
            "var s = document.createElement('script'); s.src = window.CFG.gameBase + window.CFG.gameScript;\n"
            "document.body.appendChild(s);\n", encoding="utf-8")
        (root / "redirect.html").write_text(
            '<!doctype html><html><head><meta http-equiv="refresh" content="0; url=game/shell.html"></head>'
            '<body>moving</body></html>', encoding="utf-8")
        return root

    def test_dynamic_loader_reaches_wasm_and_data(self):
        root = self.make_site()
        report = static_report(root, entry="game/shell.html")
        self.assertEqual(codes(report), [])
        self.assertEqual(report.wasm_files, ["game/game.wasm"])
        self.assertIn("game/game.js", report.resources)
        # data/ 는 로더를 실행하는 문서(game/shell.html) 기준이므로 game/data 로 잡혀야 한다.
        self.assertEqual(list(report.data_dirs), ["game/data"])

    def test_loader_name_resolved_against_document_not_script(self):
        # 'game.js' 를 JS 파일 위치(game/js/) 기준으로 풀면 game/js/game.js(없음)가 되어 오류가 났을 것이다.
        report = static_report(self.make_site(), entry="game/shell.html")
        self.assertNotIn("missing-file", codes(report))
        self.assertNotIn("game/js/game.js", report.resources)

    def test_meta_refresh_is_followed(self):
        report = static_report(self.make_site(), entry="redirect.html")
        self.assertEqual(codes(report), [])
        self.assertEqual(report.wasm_files, ["game/game.wasm"])

    def test_missing_dynamic_loader_is_error(self):
        root = self.make_site(loader_name="missing-loader.js")
        report = static_report(root, entry="game/shell.html")
        errors = [f for f in report.findings if f.level == "error"]
        self.assertIn("missing-file", [f.code for f in errors])
        self.assertTrue(any("JS 동적 스크립트" in f.message for f in errors))

    def test_require_wasm_turns_warning_into_error(self):
        root = self.make_site(loader_name="missing-loader.js")
        code, text = run_check(["--root", str(root), "--entry", "game/shell.html"])
        self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)  # 누락 로더 자체가 오류
        (root / "lonely.html").write_text("<html><body>no game</body></html>", encoding="utf-8")
        code, text = run_check(["--root", str(root), "--entry", "lonely.html"])
        self.assertEqual(code, check_web_assets.EXIT_OK, text)
        self.assertIn("no-wasm", text)
        code, text = run_check(["--root", str(root), "--entry", "lonely.html", "--require-wasm"])
        self.assertEqual(code, check_web_assets.EXIT_FINDINGS, text)
        self.assertIn("--require-wasm", text)

    def test_dynamic_loader_live_check(self):
        root = self.make_site()
        with LiveServer(root) as live:
            code, text = run_check(["--root", str(root), "--entry", "game/shell.html", "--url", live.url,
                                    "--require-wasm", "--sample-data", "-1", "--verify-hashes"])
        self.assertEqual(code, check_web_assets.EXIT_OK, text)
        self.assertIn("결과: 통과", text)


class WasmInspectTests(unittest.TestCase):
    def test_inspect_minimal_modules(self):
        plain = check_web_assets.inspect_wasm(make_fixture.make_wasm())
        self.assertTrue(plain["valid"])
        self.assertFalse(plain["shared_memory"])
        shared = check_web_assets.inspect_wasm(make_fixture.make_wasm(shared_memory=True))
        self.assertTrue(shared["valid"])
        self.assertTrue(shared["shared_memory"])
        self.assertFalse(check_web_assets.inspect_wasm(b"\0asm\x02\x00\x00\x00")["valid"])
        self.assertFalse(check_web_assets.inspect_wasm(b"")["valid"])

    def test_sha256_name_matches_fixture_content(self):
        for content in make_fixture.RESOURCES:
            self.assertTrue((FIXTURE_SITE / "game" / "data" / hashlib.sha256(content).hexdigest()).is_file())


if __name__ == "__main__":
    unittest.main()
