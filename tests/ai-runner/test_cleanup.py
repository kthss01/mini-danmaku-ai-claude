"""정리 단계 격리와 출처(dirty) 기록 테스트. 브라우저 없이 가짜 객체로 검증한다(Codex 검토 #46 P1·P2 회귀).

실행: python -m unittest discover -s tests/ai-runner -p "test_cleanup.py" -v
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import _support as S  # noqa: F401 - sys.path에 scripts/ai를 넣는다
from runner import config, orchestrator, provenance
from runner.episode import EpisodeDriver, EpisodeResult
from runner.runfiles import RunDir, RunLogger


class FakeConn:
    def __init__(self):
        self.closed = threading.Event()


class FakeBrowser:
    def __init__(self, close_result=None, close_error=None):
        self.close_calls = 0
        self._result = close_result or {"forced": [], "remaining": [], "profile_removed": True, "errors": []}
        self._error = close_error

    def close(self):
        self.close_calls += 1
        if self._error:
            raise self._error
        return self._result


class FinishIsolationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        run_dir = RunDir(Path(self._tmp.name), "20261029T000000Z-abcdef")
        self.logger = RunLogger(run_dir.logs / "runner.log", echo=False)
        self.addCleanup(self.logger.close)
        self.driver = EpisodeDriver(config.RunConfig(), run_dir, self.logger, "http://127.0.0.1:1/", "game/index.html",
                                    "chrome", "20261029T000000Z-abcdef")
        self.addCleanup(self.driver.close)
        self.run_dir = run_dir
        self.result = EpisodeResult(index=1)
        self.result.bridge_present = True

    def finish(self, browser):
        self.driver._finish(FakeConn(), browser, 1, self.result)

    def test_input_release_exception_still_closes_browser_and_collects_evidence(self):
        browser = FakeBrowser()
        with mock.patch.object(self.driver, "_release_inputs", side_effect=OSError("disk full")), \
             mock.patch.object(self.driver, "_collect_evidence") as collect:
            self.finish(browser)
        self.assertEqual(browser.close_calls, 1)
        collect.assert_called_once()
        self.assertTrue(any("입력 해제 확인 예외" in e for e in self.result.cleanup_errors))
        # 입력 해제를 확인하지 못했으므로 정리가 깨끗하다고 기록되면 안 된다.
        self.assertEqual(orchestrator.cleanup_status(self.result), "unknown")

    def test_evidence_exception_still_closes_browser(self):
        browser = FakeBrowser()
        self.result.input_release = {"released": True}
        with mock.patch.object(self.driver, "_release_inputs"), \
             mock.patch.object(self.driver, "_collect_evidence", side_effect=RuntimeError("boom")):
            self.finish(browser)
        self.assertEqual(browser.close_calls, 1)
        self.assertTrue(any("증거 수집 예외" in e for e in self.result.cleanup_errors))

    def test_browser_close_exception_is_recorded_as_unknown(self):
        browser = FakeBrowser(close_error=RuntimeError("tasklist failed"))
        self.result.input_release = {"released": True}
        with mock.patch.object(self.driver, "_release_inputs"), mock.patch.object(self.driver, "_collect_evidence"):
            self.finish(browser)
        self.assertIsNone(self.result.cleanup["remaining"])
        self.assertTrue(self.result.ended_at)
        self.assertEqual(orchestrator.cleanup_status(self.result), "unknown")

    def test_keyboard_interrupt_during_cleanup_still_closes_browser(self):
        browser = FakeBrowser()
        with mock.patch.object(self.driver, "_release_inputs", side_effect=KeyboardInterrupt), \
             mock.patch.object(self.driver, "_collect_evidence"):
            with self.assertRaises(KeyboardInterrupt):
                self.finish(browser)
        self.assertEqual(browser.close_calls, 1)

    def test_artifact_write_failure_is_recorded_not_raised(self):
        # episodes/0001이 파일이면 하위 파일을 만들 수 없다(OSError).
        (self.run_dir.episodes / "0001").write_text("not a directory", encoding="utf-8")
        event = {"type": "artifact", "name": "trace.jsonl", "encoding": "utf8", "data": "x"}
        self.driver._save_artifact(event, 1, self.result)
        self.assertTrue(any("trace.jsonl 저장 실패" in e for e in self.result.evidence_errors))
        self.assertEqual(self.result.artifacts, [])

    def test_release_check_failure_is_unknown_not_released(self):
        with mock.patch.object(self.driver, "_poll", side_effect=ValueError("bad json")), \
             mock.patch.object(self.driver, "_release_inputs", wraps=self.driver._release_inputs):
            conn = mock.Mock()
            self.driver._release_inputs(conn, 1, self.result)
        self.assertIsNone(self.result.input_release["released"])
        self.assertIn("확인 실패", self.result.input_release["detail"])


class CleanupStatusTests(unittest.TestCase):
    def result(self, **kwargs):
        r = EpisodeResult(index=1)
        r.bridge_present = kwargs.pop("bridge", True)
        r.input_release = kwargs.pop("release", {"released": True})
        r.cleanup = kwargs.pop("cleanup", {"forced": [], "remaining": [], "profile_removed": True, "errors": []})
        for key, value in kwargs.items():
            setattr(r, key, value)
        return r

    def test_clean(self):
        self.assertEqual(orchestrator.cleanup_status(self.result()), "clean")

    def test_smoke_without_bridge_is_clean(self):
        r = self.result(bridge=False, release={"released": None, "detail": "no_bridge"})
        self.assertEqual(orchestrator.cleanup_status(r), "clean")

    def test_bridge_with_unconfirmed_release_is_unknown(self):
        self.assertEqual(orchestrator.cleanup_status(self.result(release={"released": None})), "unknown")

    def test_remaining_process_or_profile_is_leak(self):
        leak = {"forced": [], "remaining": [123], "profile_removed": True, "errors": []}
        self.assertEqual(orchestrator.cleanup_status(self.result(cleanup=leak)), "leak")
        leak = {"forced": [], "remaining": [], "profile_removed": False, "errors": []}
        self.assertEqual(orchestrator.cleanup_status(self.result(cleanup=leak)), "leak")

    def test_unreadable_process_list_is_unknown_not_clean(self):
        cleanup = {"forced": [], "remaining": None, "profile_removed": True, "errors": ["프로세스 조회 실패"]}
        self.assertEqual(orchestrator.cleanup_status(self.result(cleanup=cleanup)), "unknown")

    def test_input_not_released_is_leak(self):
        self.assertEqual(orchestrator.cleanup_status(self.result(release={"released": False})), "leak")

    def test_leak_wins_over_unknown_and_server_status(self):
        self.assertEqual(orchestrator.server_cleanup_status({"port_closed": True, "process_gone": True}), "clean")
        self.assertEqual(orchestrator.server_cleanup_status({"port_closed": False, "process_gone": True}), "leak")
        self.assertEqual(orchestrator.server_cleanup_status({"port_closed": None, "process_gone": True}), "unknown")
        self.assertEqual(orchestrator.server_cleanup_status({"port_closed": True, "process_gone": True,
                                                              "error": "x"}), "unknown")


class DirtyProvenanceTests(unittest.TestCase):
    FACTS = {
        "taisei_commit": "f" * 40, "build_flavor": "release", "meson_options": [], "rules_preserved": "original",
        "build_info_sha256": "a", "wasm_sha256": "b", "build_repository_commit": "e" * 40, "build_started_at": "t",
        "build_dirty_entries": [], "build_taisei_dirty_entries": [], "packaging_dirty_entries": [],
        "web_shell_dirty_entries": [],
    }

    def block(self, dirty, **overrides):
        return provenance.code_block({**self.FACTS, **overrides}, "c" * 40, dirty)

    def test_all_clean_is_false(self):
        self.assertIs(self.block([])["dirty"], False)

    def test_dirty_build_with_clean_runner_is_not_clean(self):
        block = self.block([], build_dirty_entries=[" M scripts/build-web.ps1"], packaging_dirty_entries=["?? web/"])
        self.assertIs(block["dirty"], True)
        self.assertEqual(block["dirty_entries"], [])
        self.assertEqual(block["dirty_sources"]["build_repository"], [" M scripts/build-web.ps1"])
        self.assertEqual(block["dirty_sources"]["packaging_repository"], ["?? web/"])

    def test_dirty_taisei_worktree_or_web_shell_counts(self):
        self.assertIs(self.block([], build_taisei_dirty_entries=[" M src/a.c"])["dirty"], True)
        self.assertIs(self.block([], web_shell_dirty_entries=[" M web/game/shell.js"])["dirty"], True)

    def test_dirty_runner_checkout_counts(self):
        self.assertIs(self.block([" M scripts/ai/run.py"])["dirty"], True)

    def test_git_status_failure_is_unknown_not_clean(self):
        self.assertIsNone(self.block(None)["dirty"])
        with mock.patch.object(provenance, "_git", return_value=None):
            commit, dirty = provenance.main_commit_and_dirty()
        self.assertIsNone(dirty)

    def test_missing_provenance_field_is_unknown(self):
        self.assertIsNone(self.block([], build_taisei_dirty_entries=None)["dirty"])

    def test_dirty_wins_over_unknown(self):
        self.assertIs(self.block(None, build_dirty_entries=[" M x"])["dirty"], True)


if __name__ == "__main__":
    unittest.main()
