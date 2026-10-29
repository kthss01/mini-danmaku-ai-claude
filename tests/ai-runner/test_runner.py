"""AI 실험 실행기(scripts/ai) 테스트.

fixture 페이지(tests/ai-runner/fixture)로 시작·감시·수집·정리를 검증한다. 실제 게임과 브리지는 쓰지 않는다.
브라우저(Chrome/Edge)가 없는 환경에서는 브라우저가 필요한 테스트를 건너뛴다.

실행: python -m unittest discover -s tests/ai-runner -v
"""

from __future__ import annotations

import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import _support as S
from runner import cdp, config


class FrameTests(unittest.TestCase):
    def test_masked_roundtrip_and_lengths(self):
        for size in (0, 5, 125, 126, 70000):
            a, b = socket.socketpair()
            with a, b:
                payload = bytes(range(256)) * (size // 256 + 1)
                payload = payload[:size]
                a.sendall(cdp.encode_frame(0x1, payload))
                fin, opcode, data = cdp.read_frame(b)
                self.assertEqual((fin, opcode, data), (True, 0x1, payload))

    def test_unmasked_server_frame(self):
        a, b = socket.socketpair()
        with a, b:
            a.sendall(cdp.encode_frame(0x1, b"hello", mask=False))
            self.assertEqual(cdp.read_frame(b), (True, 0x1, b"hello"))

    def test_rejects_non_local_ws_url(self):
        with self.assertRaises(cdp.CdpError):
            cdp.CdpConnection("ws://example.com:9222/devtools/page/1")


class ArgumentTests(unittest.TestCase):
    """브라우저를 띄우지 않는 실패 경로. 잘못된 설정은 종료 코드와 run.json에 명확히 남아야 한다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.runs = self.tmp / "runs"
        self.site = S.make_site(self.tmp)

    def run_with(self, *args, site=True):
        extra = ["--site", str(self.site)] if site else []
        return S.run_cli([*extra, *args], self.runs, timeout=60)

    def test_bad_difficulty_is_exit_2(self):
        self.assertEqual(self.run_with("--difficulty", "Impossible").returncode, config.EXIT_BAD_ARGS)

    def test_seed_is_unsupported_exit_2(self):
        done = self.run_with("--seed", "7")
        self.assertEqual(done.returncode, config.EXIT_BAD_ARGS)
        self.assertIn("--seed", done.stderr)
        record = S.read_json(S.last_run_dir(self.runs) / "run.json")
        self.assertEqual(record["exit_code"], config.EXIT_BAD_ARGS)
        self.assertIn("seed", record["error"])

    def test_stage_and_spell_together_is_exit_2(self):
        self.assertEqual(self.run_with("--stage", "1", "--spell", "2").returncode, config.EXIT_BAD_ARGS)

    def test_numeric_limits_are_validated(self):
        for bad in (["--max-frames", "0"], ["--episodes", "0"], ["--wall-timeout-s", "-1"], ["--port", "70000"]):
            self.assertEqual(self.run_with(*bad).returncode, config.EXIT_BAD_ARGS, bad)

    def test_unknown_config_key_is_exit_2(self):
        cfg = self.tmp / "bad.json"
        cfg.write_text('{"nonsense": 1}', encoding="utf-8")
        done = self.run_with("--config", str(cfg))
        self.assertEqual(done.returncode, config.EXIT_BAD_ARGS)
        self.assertIn("nonsense", done.stderr)

    def test_missing_site_is_exit_3_with_record(self):
        done = S.run_cli(["--site", str(self.tmp / "nope")], self.runs, timeout=60)
        self.assertEqual(done.returncode, config.EXIT_BAD_BUILD)
        record = S.read_json(S.last_run_dir(self.runs) / "run.json")
        self.assertEqual(record["exit_code"], config.EXIT_BAD_BUILD)
        self.assertEqual(record["attempted_episodes"], 0)

    def test_flavor_mismatch_is_exit_3(self):
        done = self.run_with("--build-flavor", "developer")  # site는 release 빌드
        self.assertEqual(done.returncode, config.EXIT_BAD_BUILD)
        self.assertIn("빌드 종류 불일치", done.stderr)

    def test_stage_needs_developer_build_exit_3(self):
        done = self.run_with("--stage", "stage1")
        self.assertEqual(done.returncode, config.EXIT_BAD_BUILD)
        self.assertIn("개발자 빌드", done.stderr)

    def test_tampered_wasm_is_exit_3(self):
        (self.site / "game" / "taisei.wasm").write_bytes(b"tampered")
        done = self.run_with()
        self.assertEqual(done.returncode, config.EXIT_BAD_BUILD)
        self.assertIn("해시", done.stderr)

    def test_missing_build_info_is_exit_3(self):
        (self.site / "build-info.json").unlink()
        self.assertEqual(self.run_with().returncode, config.EXIT_BAD_BUILD)

    def test_game_args_for_developer_spell(self):
        cfg = config.parse_args(["--build-flavor", "developer", "--spell", "s1", "--difficulty", "Hard",
                                 "--shotmode", "youmuA"])
        self.assertEqual(cfg.game_args(), ["--sid", "s1", "--diff", "Hard", "--shotmode", "youmuA"])
        self.assertEqual(cfg.scenario()["kind"], "spell")


class SiteRunTests(unittest.TestCase):
    """fixture 페이지로 실제 브라우저·서버를 띄우는 테스트."""

    @classmethod
    def setUpClass(cls):
        if not S.CHROME:
            raise unittest.SkipTest("Chrome/Edge가 없어 건너뜁니다")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.runs = self.tmp / "runs"
        self.site = S.make_site(self.tmp)
        self.profiles_before = S.leftover_profiles()

    def execute(self, policy, *extra, timeout=120):
        return S.run_cli(["--site", str(self.site), "--policy", policy, "--max-frames", "120", *extra],
                         self.runs, timeout=timeout)

    def assert_clean(self):
        self.assertEqual(S.leftover_profiles() - self.profiles_before, set(), "임시 프로필이 남았습니다")
        self.assertEqual(S.leftover_browser_pids(), [], "브라우저 프로세스가 남았습니다")
        record = S.read_json(S.last_run_dir(self.runs) / "run.json")
        port = (record.get("server") or {}).get("port")
        if port:
            from runner import procs
            self.assertFalse(procs.port_open(port), "서버 포트가 열려 있습니다")

    def episode(self, index=1):
        return S.read_json(S.last_run_dir(self.runs) / "episodes" / f"{index:04d}.json")

    def test_completed_episode_is_saved(self):
        done = self.execute("fixture-idle")
        self.assertEqual(done.returncode, 0, done.stderr)
        run_dir = S.last_run_dir(self.runs)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("completed", "frame_limit"))
        self.assertTrue(ep["run"]["evaluable"])
        self.assertEqual(ep["code"]["build_flavor"], "release")
        self.assertEqual(ep["code"]["taisei_commit"], "f" * 40)
        self.assertEqual(ep["config"]["seed"]["control"], "random")
        self.assertEqual(ep["schema"], "taisei-ai-episode/1")
        self.assertEqual(ep["runner"]["cleanup_status"], "clean")
        self.assertEqual(ep["runner"]["cleanup_errors"], [])
        self.assertIs(ep["runner"]["input_release"]["released"], True)
        self.assertNotIn("status_by_runner", ep["run"])
        events = (run_dir / "episodes" / "0001.events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"episode_end"', events)
        self.assertTrue((run_dir / "build-info.json").is_file())
        summary = S.read_json(run_dir / "summary.json")
        self.assertEqual(summary["by_status"], {"completed": 1})
        self.assertTrue(summary["cleanup_ok"])
        self.assertTrue((run_dir / "logs" / "server.log").stat().st_size > 0)
        self.assertIn("fixture: first frame", (run_dir / "logs" / "browser-console.log").read_text(encoding="utf-8"))
        self.assert_clean()

    def test_wall_timeout_is_recorded_not_hung(self):
        started = time.monotonic()
        done = self.execute("fixture-hang", "--wall-timeout-s", "3")
        self.assertEqual(done.returncode, 0, done.stderr)  # 에피소드 timeout은 종료 코드 0
        self.assertLess(time.monotonic() - started, 60)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("timeout", "wall_timeout"))
        self.assertFalse(ep["run"]["evaluable"])
        self.assertTrue((S.last_run_dir(self.runs) / "episodes" / "0001" / "last-screen.png").is_file())
        self.assert_clean()

    def test_shell_error_is_error_episode(self):
        done = self.execute("fixture-crash")
        self.assertEqual(done.returncode, 0, done.stderr)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("error", "runner_error"))
        self.assertIn("abort", ep["run"]["detail"])
        self.assert_clean()

    def test_input_leak_is_detected_exit_6(self):
        done = self.execute("fixture-leak")
        self.assertEqual(done.returncode, config.EXIT_CLEANUP_FAILED, done.stderr)
        ep = self.episode()
        self.assertIs(ep["runner"]["input_release"]["released"], False)
        record = S.read_json(S.last_run_dir(self.runs) / "run.json")
        self.assertFalse(record["cleanup"]["ok"])
        self.assertEqual(record["cleanup"]["status"], "leak")
        self.assertEqual(record["cleanup"]["episodes_with_leaks"], [1])

    def test_missing_bridge_is_exit_4(self):
        done = self.execute("fixture-nobridge")
        self.assertEqual(done.returncode, config.EXIT_NO_START, done.stderr)
        ep = self.episode()
        self.assertIn("bridge_missing", ep["run"]["detail"])
        self.assertFalse(ep["runner"]["bridge_present"])
        self.assert_clean()

    def test_startup_timeout_is_exit_4(self):
        done = self.execute("fixture-stuck", "--startup-timeout-s", "3")
        self.assertEqual(done.returncode, config.EXIT_NO_START, done.stderr)
        ep = self.episode()
        self.assertEqual(ep["run"]["status"], "error")
        self.assertIn("playing", ep["run"]["detail"])
        self.assert_clean()

    def test_smoke_mode_without_bridge(self):
        done = self.execute("fixture-nobridge", "--mode", "smoke", "--smoke-duration-s", "1")
        self.assertEqual(done.returncode, 0, done.stderr)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("completed", "smoke_duration"))
        self.assertFalse(ep["run"]["evaluable"])
        self.assertFalse(ep["runner"]["bridge_present"])
        self.assert_clean()

    def test_end_is_derived_from_bridge_state_without_episode_end(self):
        done = self.execute("fixture-stageend")
        self.assertEqual(done.returncode, 0, done.stderr)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("completed", "stage_end"))
        self.assertTrue(ep["run"]["evaluable"])
        # 입력 카운터가 없는 브리지는 소유권(manual)만 증거다.
        self.assertEqual(ep["runner"]["input_release"]["basis"], "owner_state")
        self.assertIs(ep["runner"]["input_release"]["released"], True)
        states = [(t["state"], t["reason"]) for t in ep["owner_transitions"]]
        self.assertIn(("ai_active", "none"), states)
        self.assertIn(("ai_suspended", "stage_end"), states)
        self.assertEqual(ep["episode_id"], 1)
        self.assertGreaterEqual(ep["final"]["last_frame"], 120)
        self.assert_clean()

    def test_frame_limit_is_detected_by_runner(self):
        done = self.execute("fixture-framecap")
        self.assertEqual(done.returncode, 0, done.stderr)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("completed", "frame_limit"))
        self.assertIn("runner_detected", ep["run"]["detail"])
        progress = ep["runner"]["frame_progress"]
        self.assertEqual(progress["limit_detected_by"], "runner")
        self.assertIsNotNone(progress["pre_enable_frame"])
        self.assertGreaterEqual(progress["elapsed_frames"], progress["max_frames"])
        self.assertEqual(progress["exceeded_by"], progress["elapsed_frames"] - progress["max_frames"])

    def test_user_key_takeover_is_aborted(self):
        done = self.execute("fixture-userkey")
        self.assertEqual(done.returncode, 0, done.stderr)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("aborted", "user_abort"))
        self.assertFalse(ep["run"]["evaluable"])

    def test_enable_rejected_not_playing_is_error(self):
        done = self.execute("fixture-notplaying")
        self.assertEqual(done.returncode, 0, done.stderr)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("error", "runner_error"))
        self.assertIn("not_playing", ep["run"]["detail"])
        self.assertEqual(ep["run"]["error_message"], ep["run"]["detail"])

    def test_policy_load_failure_is_policy_error(self):
        done = self.execute("fixture-badpolicy")
        self.assertEqual(done.returncode, 0, done.stderr)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("error", "policy_error"))
        self.assertIn("fixture-badpolicy", ep["run"]["detail"])
        self.assert_clean()

    def test_policy_none_skips_load_policy(self):
        done = self.execute("none")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.episode()["run"]["status"], "completed")

    def test_artifact_events_are_saved(self):
        done = self.execute("fixture-artifact")
        self.assertEqual(done.returncode, 0, done.stderr)
        trace = S.last_run_dir(self.runs) / "episodes" / "0001" / "trace.jsonl"
        self.assertEqual(trace.read_text(encoding="utf-8"), '{"frame":1}\n{"frame":2}\n')
        self.assertIn("episodes/0001/trace.jsonl", self.episode()["evidence"]["artifacts"])

    def test_multiple_episodes_use_fresh_profiles(self):
        done = self.execute("fixture-idle", "--episodes", "2")
        self.assertEqual(done.returncode, 0, done.stderr)
        summary = S.read_json(S.last_run_dir(self.runs) / "summary.json")
        self.assertEqual((summary["requested"], summary["attempted"]), (2, 2))
        self.assert_clean()

    def test_three_consecutive_runs_leak_nothing(self):
        for _ in range(3):
            done = self.execute("fixture-idle")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assert_clean()
        self.assertEqual(len([p for p in self.runs.iterdir() if p.is_dir()]), 3)

    @unittest.skipUnless(sys.platform == "win32", "CTRL_BREAK 신호는 Windows 전용")
    def test_ctrl_break_aborts_and_cleans_up(self):
        proc = subprocess.Popen(
            [sys.executable, "-I", str(S.RUN_PY), "--run-root", str(self.runs), "--site", str(self.site),
             "--policy", "fixture-hang", "--wall-timeout-s", "120", "--max-frames", "120"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                logs = list(self.runs.glob("*/logs/runner.log")) if self.runs.exists() else []
                if logs and "브라우저 " in logs[0].read_text(encoding="utf-8") and S.leftover_browser_pids():
                    break
                time.sleep(0.5)
            time.sleep(2)  # enable 이후 감시 루프에 들어가도록 잠시 둔다.
            import signal
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            proc.communicate(timeout=60)
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertEqual(proc.returncode, config.EXIT_ABORTED)
        ep = self.episode()
        self.assertEqual((ep["run"]["status"], ep["run"]["reason"]), ("aborted", "user_abort"))
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
