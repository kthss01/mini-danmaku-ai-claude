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
        # 저장 경로가 디렉터리면 파일을 열 수 없다(OSError). trace와 일반 artifact 두 경로 모두 확인한다.
        (self.run_dir.episodes / "0001.trace.jsonl").mkdir()
        (self.run_dir.episodes / "0001").write_text("not a directory", encoding="utf-8")
        for name in ("trace.jsonl", "other.bin"):
            event = {"type": "artifact", "name": name, "encoding": "utf8", "data": "x"}
            self.driver._save_artifact(event, 1, self.result)
            self.assertTrue(any(f"{name} 저장 실패" in e for e in self.result.evidence_errors), name)
        self.assertNotIn("trace", self.result.evidence)
        self.assertEqual(self.result.artifacts, [])

    def test_release_check_failure_is_unknown_not_released(self):
        with mock.patch.object(self.driver, "_poll", side_effect=ValueError("bad json")), \
             mock.patch.object(self.driver, "_release_inputs", wraps=self.driver._release_inputs):
            conn = mock.Mock()
            self.driver._release_inputs(conn, 1, self.result)
        self.assertIsNone(self.result.input_release["released"])
        self.assertIn("확인 실패", self.result.input_release["detail"])


class ProcessLookupTests(unittest.TestCase):
    def test_failed_lookup_command_raises_instead_of_empty_list(self):
        from runner import procs
        failed = mock.Mock(returncode=1, stdout="", stderr="Get-CimInstance : 액세스 거부")
        with mock.patch.object(procs.subprocess, "run", return_value=failed):
            with self.assertRaises(procs.ProcessLookupFailed):
                procs.find_pids_by_cmdline("taisei-ai-profile-x")

    def test_failed_pid_check_raises(self):
        from runner import procs
        failed = mock.Mock(returncode=1, stdout="", stderr="x")
        with mock.patch.object(procs, "IS_WINDOWS", True), mock.patch.object(procs.subprocess, "run", return_value=failed):
            with self.assertRaises(procs.ProcessLookupFailed):
                procs.pid_alive(123)

    def test_server_liveness_uses_popen_poll_not_external_command(self):
        from runner import procs, server as server_mod
        with tempfile.TemporaryDirectory() as tmp:
            srv = server_mod.SiteServer(Path(tmp), Path(tmp) / "s.log")
            srv.process = mock.Mock(pid=123)
            srv.process.poll.return_value = None   # kill 뒤에도 살아 있음
            srv.process.wait.side_effect = server_mod.subprocess.TimeoutExpired("x", 1)
            srv.port = None
            with mock.patch.object(procs, "kill_tree"), \
                 mock.patch.object(procs.subprocess, "run", side_effect=AssertionError("외부 명령을 부르면 안 됨")):
                info = srv.stop()
        self.assertIs(info["process_gone"], False)
        self.assertEqual(orchestrator.server_cleanup_status(info), "leak")

    def test_browser_own_process_alive_is_counted_even_if_lookup_is_empty(self):
        import shutil
        from runner import browser as browser_mod, procs
        b = browser_mod.Browser("chrome", True)
        b.process = mock.Mock(pid=4242)
        b.process.poll.return_value = None
        b.process.wait.side_effect = browser_mod.subprocess.TimeoutExpired("x", 1)
        try:
            with mock.patch.object(procs, "find_pids_by_cmdline", return_value=[]), \
                 mock.patch.object(procs, "kill_tree"):
                info = b.close()
        finally:
            shutil.rmtree(b.profile_dir, ignore_errors=True)
        self.assertEqual(info["remaining"], [4242])
        r = EpisodeResult(index=1)
        r.cleanup = info
        r.input_release = {"released": True}
        self.assertEqual(orchestrator.cleanup_status(r), "leak")

    def test_lookup_success_with_no_match_is_empty(self):
        from runner import procs
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(procs.subprocess, "run", return_value=ok):
            self.assertEqual(procs.find_pids_by_cmdline("taisei-ai-profile-x"), [])

    def test_browser_close_reports_unknown_when_lookup_fails(self):
        from runner import browser as browser_mod, procs
        b = browser_mod.Browser("chrome", True)
        try:
            with mock.patch.object(procs, "find_pids_by_cmdline", side_effect=procs.ProcessLookupFailed("x")):
                info = b.close()
        finally:
            import shutil
            shutil.rmtree(b.profile_dir, ignore_errors=True)
        self.assertIsNone(info["remaining"])
        self.assertTrue(info["errors"])


def _fake_server_class(stopped):
    class FakeServer:
        port = 1
        process = None
        url = "http://127.0.0.1:1/"

        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            stopped.append(True)
            return {"pid": None, "port": 1, "port_closed": True, "process_gone": True}

    return FakeServer


class FakeDriver:
    def __init__(self, *args, **kwargs):
        pass

    def run(self, index):
        r = EpisodeResult(index=index)
        r.status, r.reason = "completed", "smoke_duration"
        r.cleanup = {"forced": [], "remaining": [], "profile_removed": True, "errors": []}
        return r

    def close(self):
        raise OSError("close failed")


class BestEffortLoggingTests(unittest.TestCase):
    def test_logger_write_failure_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = RunLogger(Path(tmp) / "runner.log", echo=False)
            broken = mock.Mock()
            broken.write.side_effect = OSError("disk full")
            logger._file = broken
            logger.log("메시지", "ERROR")  # 예외 없이 끝나야 한다
            self.assertEqual(logger.write_failures, 1)
            logger.close()

    def test_finish_closes_browser_even_when_logging_is_broken(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)  # 먼저 등록해야 아래 파일 닫기 뒤에 지워진다(Windows는 열린 파일을 못 지운다)
        run_dir = RunDir(Path(tmp.name), "20261029T000000Z-abcdef")
        logger = RunLogger(run_dir.logs / "runner.log", echo=False)
        self.addCleanup(logger.close)
        broken = mock.Mock()
        broken.write.side_effect = OSError("disk full")
        logger._file = broken
        driver = EpisodeDriver(config.RunConfig(), run_dir, logger, "http://127.0.0.1:1/", "game/index.html",
                               "chrome", "20261029T000000Z-abcdef")
        self.addCleanup(driver.close)
        browser = FakeBrowser()
        result = EpisodeResult(index=1)
        with mock.patch.object(driver, "_release_inputs", side_effect=OSError("disk full")),              mock.patch.object(driver, "_collect_evidence"):
            driver._finish(FakeConn(), browser, 1, result)
        self.assertEqual(browser.close_calls, 1)
        self.assertTrue(result.cleanup_errors)

    def run_with_fakes(self, **patches):
        stopped = []
        with tempfile.TemporaryDirectory() as tmp:
            site = S.make_site(Path(tmp))
            with mock.patch.object(orchestrator, "SiteServer", _fake_server_class(stopped)), \
                 mock.patch.object(orchestrator, "EpisodeDriver", FakeDriver), \
                 mock.patch.object(orchestrator, "find_browser", return_value="chrome"):
                for name, value in patches.items():
                    mock.patch.object(orchestrator, name, **value).start()
                self.addCleanup(mock.patch.stopall)
                code = orchestrator.run(["--site", str(site), "--run-root", str(Path(tmp) / "runs"),
                                         "--mode", "smoke"])
            manifest = S.read_json(S.last_run_dir(Path(tmp) / "runs") / "run.json")
        self.last_manifest = manifest
        return code, stopped

    def test_driver_close_failure_still_stops_server(self):
        code, stopped = self.run_with_fakes()
        self.assertEqual(stopped, [True])
        self.assertEqual(code, 0)
        self.assertEqual(self.last_manifest["exit_code"], 0)

    def test_summary_failure_is_exit_5_in_both_return_code_and_saved_manifest(self):
        code, stopped = self.run_with_fakes(_write_summary={"side_effect": OSError("summary failed")})
        self.assertEqual(stopped, [True])
        self.assertEqual(code, config.EXIT_RUNNER_ERROR)
        # run.json은 쓰기에 성공했으므로 프로세스 반환 코드와 같은 최종 종료 코드가 들어 있어야 한다.
        self.assertTrue(self.last_manifest["finished"])
        self.assertEqual(self.last_manifest["exit_code"], config.EXIT_RUNNER_ERROR)
        self.assertIn("summary.json", self.last_manifest["error"])

    def test_run_json_write_failure_is_exit_5_via_return_code(self):
        # run.json 쓰기만 실패하는 경우: 기록은 남길 수 없으므로 반환 코드로만 알린다(첫 호출들은 성공해야 run.json이 시작 시 생성된다).
        real_write = orchestrator.write_json
        calls = {"n": 0}

        def flaky(path, value):
            calls["n"] += 1
            if value.get("finished") is True and Path(path).name == "run.json":
                raise OSError("run.json failed")
            return real_write(path, value)

        stopped = []
        with tempfile.TemporaryDirectory() as tmp:
            site = S.make_site(Path(tmp))
            with mock.patch.object(orchestrator, "SiteServer", _fake_server_class(stopped)), \
                 mock.patch.object(orchestrator, "EpisodeDriver", FakeDriver), \
                 mock.patch.object(orchestrator, "find_browser", return_value="chrome"), \
                 mock.patch.object(orchestrator, "write_json", side_effect=flaky):
                code = orchestrator.run(["--site", str(site), "--run-root", str(Path(tmp) / "runs"),
                                         "--mode", "smoke"])
        self.assertEqual(stopped, [True])
        self.assertEqual(code, config.EXIT_RUNNER_ERROR)


class FrameBookkeepingTests(unittest.TestCase):
    def test_cleanup_poll_does_not_overwrite_limit_frame(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run_dir = RunDir(Path(tmp.name), "20261029T000000Z-abcdef")
        logger = RunLogger(run_dir.logs / "runner.log", echo=False)
        self.addCleanup(logger.close)
        driver = EpisodeDriver(config.RunConfig(), run_dir, logger, "http://x/", "game/index.html", "chrome",
                               "20261029T000000Z-abcdef")
        self.addCleanup(driver.close)
        conn = mock.Mock()
        conn.drain_events.return_value = []
        result = EpisodeResult(index=1)
        frames = iter([100, 220, 9999])
        conn.evaluate.side_effect = lambda *a, **k: {"shell": None, "ai": {"lastFrame": next(frames)},
                                                      "events": [], "dropped": 0, "bridge": True, "hooked": True}
        driver._poll(conn, 1, result)
        driver._poll(conn, 1, result)
        self.assertEqual(result.end_frame, 220)
        result.frame_locked = True
        driver._poll(conn, 1, result)        # 정리 단계의 폴링
        self.assertEqual(result.end_frame, 220)
        self.assertEqual(result.cleanup_frame, 9999)

    def test_baseline_prefers_pre_enable_sample(self):
        r = EpisodeResult(index=1)
        r.enable_frame, r.pre_enable_frame = 50, 40
        self.assertEqual(EpisodeDriver._baseline(r), 40)
        r.pre_enable_frame = None
        self.assertEqual(EpisodeDriver._baseline(r), 50)


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

    def test_packaged_ai_files_dirty_counts_only_when_packaged(self):
        self.assertIs(self.block([], ai_packaged=True, ai_dirty_entries=[" M ai/bridge/taisei-ai-bridge.mjs"])["dirty"], True)
        self.assertIsNone(self.block([], ai_packaged=True, ai_dirty_entries=None)["dirty"])
        self.assertIs(self.block([], ai_packaged=True, ai_dirty_entries=[])["dirty"], False)
        # ai/를 패키징하지 않은 빌드(이전 빌드)에서는 이 출처를 보지 않는다.
        self.assertIs(self.block([], ai_packaged=False, ai_dirty_entries=None)["dirty"], False)

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
