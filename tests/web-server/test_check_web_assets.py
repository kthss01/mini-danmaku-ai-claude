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
        self.assertIn("case-mismatch", codes(static_report(root)))

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
