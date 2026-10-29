"""평가 도구 검증 (fixture 기반). 실제 게임 결과가 아니라 가정한 계약으로 만든 합성 데이터를 쓴다.

    python -m unittest discover -s tests/ai-evaluation -v
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "evaluation"))
sys.path.insert(0, HERE)

import fixture_builder as fb  # noqa: E402
from taisei_eval import cli, compare, judge, loader, pipeline, plan, schema_lite, stats, summarize  # noqa: E402

POL = ("avoid-v1", "t-0")


def hash_tree(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def one(self, spec, policy=POL, name="20261029T000000Z-aaaaaa", **kw):
        """에피소드 1개짜리 run을 만들어 평가하고 (결과, 평가 레코드)를 돌려준다."""
        d = fb.build_policy_run(self.tmp, name, policy, [spec], **kw)
        res = pipeline.evaluate_run(d)
        return res, res["episodes"][0]


class StatsTests(unittest.TestCase):
    def test_percentile_nearest_rank(self):
        v = list(range(1, 101))
        self.assertEqual(stats.percentile(v, 50), 50)
        self.assertEqual(stats.percentile(v, 95), 95)
        self.assertEqual(stats.percentile(v, 100), 100)
        self.assertIsNone(stats.percentile([], 50))
        self.assertEqual(stats.percentile([5], 95), 5)

    def test_wilson_known_values(self):
        lo, hi = stats.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)
        lo, hi = stats.wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=3)
        self.assertIsNone(stats.wilson(0, 0))


class SchemaTests(Base):
    def test_fixture_files_pass_schemas(self):
        runs = fb.build_sample(self.tmp)
        for d in runs.values():
            _, errs, items, _ = loader.load_run(d)
            self.assertEqual(errs, [])
            for le in items.values():
                self.assertEqual(le.schema_errors, [])
                self.assertEqual(le.trace_errors, [])

    def test_output_validates_against_schema(self):
        runs = fb.build_sample(self.tmp)
        for d in runs.values():
            res = pipeline.evaluate_run(d)
            self.assertEqual(schema_lite.validate(res, "evaluation.schema.json"), [])
        cmp = compare.compare(list(runs.values()))
        self.assertEqual(schema_lite.validate(cmp, "comparison.schema.json"), [])

    def test_schema_rejects_bad_input(self):
        self.assertTrue(schema_lite.validate({"schema": "taisei-ai-episode/1"}, "episode.schema.json"))
        bad = {"frame": -1}
        self.assertTrue(schema_lite.validate(bad, "trace.schema.json"))
        ep = {"schema": "taisei-ai-episode/1", "run_id": "x", "experiment_id": "e", "episode_index": 1, "code": {}, "config": {},
              "run": {"status": "invalid"}}
        errs = schema_lite.validate(ep, "episode.schema.json")
        self.assertTrue(any("run_id" in e for e in errs))
        self.assertTrue(any("status" in e for e in errs))


class JudgeTests(Base):
    def test_clean_capture(self):
        _, e = self.one({"t": "survive", "n": 300})
        self.assertEqual((e["run"]["status"], e["run"]["reason"]), ("completed", "spell_end"))
        self.assertTrue(e["run"]["evaluable"])
        self.assertTrue(e["result"]["survived"])
        self.assertTrue(e["result"]["pattern_captured"])
        self.assertIsNone(e["result"]["stage_cleared"])
        self.assertEqual(e["metrics"]["hits"], 0)
        self.assertEqual(e["metrics"]["frames_survived"], 300)
        self.assertEqual(e["metrics"]["seconds_survived"], 5.0)

    def test_deathbomb_survives_but_not_captured(self):
        _, e = self.one({"t": "survive", "hits": [100], "hit_outcome": "deathbomb", "n": 300})
        types = [x["type"] for x in e["events"]]
        self.assertEqual(types, ["hit", "deathbomb"])
        self.assertTrue(e["result"]["survived"])
        self.assertFalse(e["result"]["pattern_captured"])
        m = e["metrics"]
        self.assertEqual((m["hits"], m["deaths"], m["deathbombs"], m["bombs_deathbomb"], m["bombs_policy"]), (1, 0, 1, 1, 0))
        self.assertTrue(e["quality"]["counters_check"]["consistent"])

    def test_policy_bomb_is_distinguished_from_deathbomb(self):
        _, e = self.one({"t": "survive", "bombs": [100], "n": 300})
        m = e["metrics"]
        self.assertEqual((m["bombs_policy"], m["bombs_deathbomb"], m["hits"]), (1, 0, 0))
        self.assertTrue(e["result"]["survived"])
        self.assertFalse(e["result"]["pattern_captured"])  # 봄을 썼으므로 캡처 아님

    def test_death_ends_survival_at_death_frame(self):
        _, e = self.one({"t": "defeat", "hits": [60], "n": 200})
        self.assertEqual((e["run"]["status"], e["run"]["reason"]), ("completed", "game_over"))
        self.assertFalse(e["result"]["survived"])
        self.assertEqual(e["result"]["first_death_frame"], 68)
        self.assertEqual(e["metrics"]["frames_survived"], 68)
        self.assertEqual(e["metrics"]["deaths"], 1)
        self.assertEqual(e["result"]["gameover_type"], "DEFEAT")

    def test_frame_limit_is_survival_not_capture(self):
        _, e = self.one({"t": "limit"}, limits={"max_frames": 200, "wall_timeout_s": 60})
        self.assertEqual(e["run"]["reason"], "frame_limit")
        self.assertTrue(e["result"]["survived"])
        self.assertFalse(e["result"]["pattern_captured"])

    def test_stage_clear_requires_no_continue(self):
        _, e = self.one({"t": "survive", "n": 300}, kind="stage")
        self.assertEqual(e["run"]["reason"], "stage_end")
        self.assertTrue(e["result"]["stage_cleared"])
        self.assertIsNone(e["result"]["pattern_captured"])

    def test_runner_failures_are_kept_and_not_evaluable(self):
        for t, status, reason in (("timeout", "timeout", "wall_timeout"), ("error", "error", "runner_error"), ("aborted", "aborted", "user_abort")):
            _, e = self.one({"t": t}, name="20261029T000000Z-aaaaaa")
            self.assertEqual((e["run"]["status"], e["run"]["reason"]), (status, reason), t)
            self.assertFalse(e["run"]["evaluable"])
            self.assertIsNone(e["result"])
            self.assertFalse(e["run"]["status_by_runner"]["overridden"])
            self.tearDown()
            self.setUp()

    def test_missing_and_unreadable_files_become_missing_status(self):
        d = fb.build_policy_run(self.tmp, "20261029T000000Z-aaaaaa", POL,
                                [{"t": "survive"}, {"t": "missing"}, {"t": "unreadable"}, {"t": "survive"}])
        res = pipeline.evaluate_run(d)
        by = {e["ref"]["episode_index"]: e for e in res["episodes"]}
        self.assertEqual(len(by), 4)
        self.assertEqual((by[2]["run"]["status"], by[2]["run"]["reason"]), ("missing", "episode_file_missing"))
        self.assertEqual((by[3]["run"]["status"], by[3]["run"]["reason"]), ("missing", "episode_file_unreadable"))
        g = res["groups"][0]
        self.assertEqual(g["counts"]["started"], 4)
        self.assertEqual(g["counts"]["evaluable"], 2)
        self.assertEqual(g["rates"]["survive_all"]["n"], 4)  # 누락도 분모에 남는다
        self.assertEqual(g["rates"]["survive_evaluable"]["n"], 2)
        self.assertEqual(g["rates"]["survive_all"]["k"], 2)

    def test_completed_without_trace_is_invalid_with_runner_status_kept(self):
        _, e = self.one({"t": "trace_missing"})
        self.assertEqual((e["run"]["status"], e["run"]["reason"]), ("invalid", "observation_invalid"))
        self.assertEqual(e["run"]["status_by_runner"], {"status": "completed", "reason": "spell_end", "overridden": True})

    def test_cheat_flags_make_invalid_rule_violation(self):
        _, e = self.one({"t": "survive", "cheat": 1})
        self.assertEqual((e["run"]["status"], e["run"]["reason"]), ("invalid", "rule_violation"))
        self.assertIn("iddqd", e["quality"]["rule_flags"])
        self.assertIsNone(e["result"])

    def test_cheat_events_make_invalid(self):
        _, e = self.one({"t": "survive", "cheat_events_at": 50})
        self.assertEqual(e["run"]["reason"], "rule_violation")
        self.assertIn("cheat_events", e["quality"]["rule_flags"])

    def test_developer_flag_bit_is_not_violation(self):
        _, e = self.one({"t": "survive", "cheat": 8}, flavor="developer")
        self.assertEqual(e["run"]["status"], "completed")
        self.assertEqual(e["build_flavor"], "developer")

    def test_unexpected_pause_invalidates_and_excludes_pause_from_fps(self):
        d = fb.build_policy_run(self.tmp, "20261029T000000Z-aaaaaa", POL, [{"t": "survive", "n": 300, "pause_at": 100}])
        # 일시정지 전환 기록 추가(브리지 onEvent)
        p = os.path.join(d, "episodes", "0001.json")
        with open(p, encoding="utf-8") as fh:
            ep = json.load(fh)
        ep["owner_transitions"] = [{"frame": 100, "state": "ai_suspended", "reason": "pause"}, {"frame": 101, "state": "ai_active", "reason": "none"}]
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(ep, fh)
        e = pipeline.evaluate_run(d)["episodes"][0]
        self.assertEqual((e["run"]["status"], e["run"]["reason"], e["run"]["reason_code"]), ("invalid", "unexpected_pause", "pause"))
        self.assertEqual([x["type"] for x in e["events"] if x["type"] in ("suspend", "resume")], ["suspend", "resume"])
        # 일시정지 구간 3초를 뺀 실행 속도는 약 60 fps
        self.assertAlmostEqual(e["metrics"]["sim_fps"]["mean"], 60.0, delta=0.5)

    def test_counter_mismatch_is_observation_invalid(self):
        _, e = self.one({"t": "survive", "n": 300, "mismatch": True})
        self.assertEqual((e["run"]["status"], e["run"]["reason"]), ("invalid", "observation_invalid"))
        self.assertFalse(e["quality"]["counters_check"]["consistent"])

    def test_trace_gap_is_observation_invalid(self):
        _, e = self.one({"t": "survive", "n": 300, "gap_at": 120})
        self.assertEqual(e["run"]["reason"], "observation_invalid")
        self.assertEqual(e["quality"]["frame_gaps"], 1)

    def test_seed_required_but_random_is_unsupported(self):
        _, e = self.one({"t": "seed_unsupported", "n": 300})
        self.assertEqual((e["run"]["status"], e["run"]["reason"]), ("unsupported", "seed_unsupported"))
        self.assertFalse(e["run"]["evaluable"])

    def test_owner_transition_reasons(self):
        cases = [("policy_error", "manual", "error", "policy_error"), ("bridge_error", "manual", "error", "runner_error"),
                 ("user_input", "manual", "aborted", "user_abort"), ("focus_lost", "ai_suspended", "invalid", "unexpected_pause")]
        for i, (reason, state, status, why) in enumerate(cases):
            with tempfile.TemporaryDirectory() as td:
                d = fb.build_policy_run(td, "20261029T000000Z-aaaaaa", POL,
                                        [{"t": "transition", "n": 600, "transitions": [{"frame": 50, "state": state, "reason": reason}]}])
                e = pipeline.evaluate_run(d)["episodes"][0]
                self.assertEqual((e["run"]["status"], e["run"]["reason"], e["run"]["reason_code"]), (status, why, reason), reason)

    def test_dialog_and_stage_end_transitions_do_not_change_status(self):
        d = fb.build_policy_run(self.tmp, "20261029T000000Z-aaaaaa", POL,
                                [{"t": "transition", "n": 600, "transitions": [{"frame": 50, "state": "ai_suspended", "reason": "dialog"},
                                                                              {"frame": 60, "state": "ai_active", "reason": "none"}]}])
        e = pipeline.evaluate_run(d)["episodes"][0]
        self.assertEqual((e["run"]["status"], e["run"]["reason"]), ("completed", "frame_limit"))

    def test_overflow_keeps_evaluable_but_marks_incomplete(self):
        _, e = self.one({"t": "survive", "n": 300, "overflow": range(100, 110)})
        self.assertTrue(e["run"]["evaluable"])
        self.assertFalse(e["quality"]["observation_complete"])
        self.assertEqual(e["quality"]["overflow_frames"], 10)
        self.assertEqual(e["quality"]["overflow_kinds"], ["bullets"])

    def test_ended_without_cause_is_invalid(self):
        _, e = self.one({"t": "survive", "n": 100, "end": "none"})
        self.assertEqual(e["run"]["reason"], "observation_invalid")

    def test_uncounted_death_is_separate(self):
        tr = fb.make_trace(200, hits=[50], hit_outcome="death", end="win")
        for r in tr:
            if r["frame"] >= 58:
                r["ev_death_uncounted"] = 1
        ev = judge.derive_events(tr)
        d = [e for e in ev if e["type"] == "death"][0]
        self.assertFalse(d["counted"])
        m = judge._metrics(tr, ev, [])
        self.assertEqual((m["deaths"], m["uncounted_deaths"]), (0, 1))

    def test_metrics_values(self):
        _, e = self.one({"t": "survive", "n": 200})
        m = e["metrics"]
        self.assertEqual(m["input_lag_frames"]["p50"], 1)
        self.assertEqual(m["input_lag_frames"]["max"], 1)
        self.assertEqual(m["decision_ms"]["n"], 200)
        self.assertEqual(m["decision_ms"]["over_policy_budget"], 0)
        self.assertAlmostEqual(m["sim_fps"]["mean"], 60.0, delta=0.5)
        self.assertEqual(m["sim_fps"]["below_60_ratio"], 0.0)
        self.assertGreater(m["shot_hold_ratio"], 0.9)

    def test_decision_budget_counts(self):
        tr = fb.make_trace(100, end="win")
        for i, r in enumerate(tr):
            r["decision_ms"] = 1.0 if i < 90 else (5.0 if i < 99 else 20.0)
        dec, _ = judge._decision_stats(tr)
        self.assertEqual((dec["over_policy_budget"], dec["over_frame_budget"]), (10, 1))
        self.assertEqual(dec["max"], 20.0)
        self.assertEqual(dec["p95"], 5.0)

    def test_slow_sim_is_flagged(self):
        _, e = self.one({"t": "survive", "n": 300, "ms_per_frame": 25.0})
        self.assertAlmostEqual(e["metrics"]["sim_fps"]["mean"], 40.0, delta=0.5)
        self.assertEqual(e["metrics"]["sim_fps"]["below_60_ratio"], 1.0)

    def test_unavailable_metrics_are_listed(self):
        _, e = self.one({"t": "survive", "n": 100, "skip_decision": True})
        self.assertIn("decision_ms", e["metrics"]["unavailable"])
        self.assertIsNone(e["metrics"]["decision_ms"])


class GroupTests(Base):
    def test_both_denominators_and_status_counts(self):
        plan_ = [{"t": "survive", "n": 300}, {"t": "defeat", "hits": [60], "n": 200}, {"t": "timeout"}, {"t": "error"},
                 {"t": "aborted"}, {"t": "missing"}, {"t": "survive", "cheat": 1}, {"t": "survive", "n": 300, "overflow": [10]}]
        d = fb.build_policy_run(self.tmp, "20261029T000000Z-aaaaaa", POL, plan_)
        g = pipeline.evaluate_run(d)["groups"][0]
        c = g["counts"]
        self.assertEqual(c["started"], 8)
        self.assertEqual(c["evaluable"], 3)
        self.assertEqual(c["by_status"], {"completed": 3, "timeout": 1, "error": 1, "aborted": 1, "missing": 1, "invalid": 1})
        self.assertEqual((g["rates"]["survive_all"]["k"], g["rates"]["survive_all"]["n"]), (2, 8))
        self.assertEqual((g["rates"]["survive_evaluable"]["k"], g["rates"]["survive_evaluable"]["n"]), (2, 3))
        self.assertEqual(g["rates"]["survive_evaluable_complete_obs"]["n"], 2)
        self.assertEqual(g["rates"]["survive_evaluable_incomplete_obs"]["n"], 1)
        self.assertEqual(g["counts"]["observation_incomplete"], 1)
        self.assertEqual(g["reproducibility"], "not_verified")
        self.assertEqual(g["rates"]["capture_all"]["n"], 8)

    def test_seed_designs(self):
        def rec(control, requested):
            return {"seed": {"control": control, "requested": requested}}
        self.assertEqual(summarize.seed_design([rec("random", None)] * 3)[0], "uncontrolled")
        self.assertEqual(summarize.seed_design([rec("set", 5)] * 5)[0], "fixed_seed_repeat")
        self.assertEqual(summarize.seed_design([rec("set", 5)])[0], "single_seed")
        d, info = summarize.seed_design([rec("set", s) for s in (1, 2, 3, 1)])
        self.assertEqual((d, info["distinct_seeds"]), ("multi_seed", 3))
        self.assertEqual(summarize.seed_design([rec("random", None), rec("set", 1)])[0], "mixed")
        self.assertEqual(summarize.seed_design([rec("replay", None)])[0], "replay")

    def test_same_seed_repeat_agreement_is_observation_only(self):
        d = os.path.join(self.tmp, "20261029T000000Z-aaaaaa")
        fb.write_run_json(d, "20261029T000000Z-aaaaaa", POL, 4)
        for i, hits in enumerate(([60], [60], [80], [80]), 1):
            seed = 7 if i <= 2 else 8
            tr = fb.make_trace(200, hits=hits, end="defeat")
            fb.write_episode(d, "20261029T000000Z-aaaaaa", i, policy=POL, seed=seed, trace=tr, runner_reason="game_over", final_go="DEFEAT")
        g = pipeline.evaluate_run(d)["groups"][0]
        self.assertEqual(g["seed_design"], "multi_seed")
        self.assertEqual(g["comparison_class"], "controlled")
        self.assertEqual(g["same_seed_agreement"]["seeds_with_repeats"], 2)
        self.assertEqual(g["same_seed_agreement"]["agreeing"], 2)
        self.assertEqual(g["reproducibility"], "not_verified")

    def test_uncontrolled_group_is_exploratory_with_caveat(self):
        d = fb.build_policy_run(self.tmp, "20261029T000000Z-aaaaaa", POL, [{"t": "survive"}])
        g = pipeline.evaluate_run(d)["groups"][0]
        self.assertEqual(g["comparison_class"], "exploratory")
        self.assertTrue(any("탐색 비교" in c for c in g["caveats"]))
        self.assertTrue(any("30개 미만" in c for c in g["caveats"]))

    def test_developer_build_caveat(self):
        d = fb.build_policy_run(self.tmp, "20261029T000000Z-aaaaaa", POL, [{"t": "survive"}], flavor="developer")
        g = pipeline.evaluate_run(d)["groups"][0]
        self.assertTrue(any("개발자 빌드" in c for c in g["caveats"]))

    def test_requested_unknown_without_run_json(self):
        d = fb.build_policy_run(self.tmp, "20261029T000000Z-aaaaaa", POL, [{"t": "survive"}, {"t": "survive"}])
        os.remove(os.path.join(d, "run.json"))
        res = pipeline.evaluate_run(d)
        self.assertFalse(res["source"]["requested_known"])
        self.assertEqual(len(res["episodes"]), 2)
        self.assertTrue(res["source"]["run_json_problems"])


class FailureTests(Base):
    def test_pre_hit_window_has_actions_and_nearest_bullet(self):
        res, e = self.one({"t": "defeat", "hits": [100], "n": 200, "hold": "move"})
        self.assertEqual(len(res["failures"]), 1)
        f = res["failures"][0]
        self.assertEqual(f["event"]["frame"], 100)
        self.assertEqual(f["window"], {"start_frame": 40, "end_frame": 100, "frames": 61})
        self.assertTrue(f["actions"])
        self.assertLessEqual(f["nearest_bullet"]["distance"], 0.0)
        self.assertEqual(f["evidence"]["trace"], "episodes/0001.trace.jsonl")
        self.assertEqual(f["policy"], "avoid-v1")

    def test_tags(self):
        res, _ = self.one({"t": "defeat", "hits": [100], "n": 200, "hold": "idle", "overflow": [90], "missing_from": 80,
                           "mode_conservative": [95], "decision_ms": 30.0})
        tags = set(res["failures"][0]["tags"])
        self.assertTrue({"observation_incomplete", "action_sync_degraded", "conservative_mode", "decision_over_frame_budget",
                         "no_movement_input"} <= tags, tags)

    def test_no_failures_for_non_evaluable(self):
        res, _ = self.one({"t": "timeout"})
        self.assertEqual(res["failures"], [])


class CompareTests(Base):
    def test_baseline_vs_policy_exploratory_and_interleaved(self):
        runs = fb.build_sample(self.tmp)
        cmp = compare.compare(list(runs.values()))
        self.assertEqual(len(cmp["buckets"]), 1)
        b = cmp["buckets"][0]
        self.assertEqual(b["comparison_class"], "exploratory")
        self.assertEqual({p["name"] for p in b["policies"]}, {"idle", "simple-move", "avoid-v1"})
        self.assertEqual({(d["policy"], d["vs"]) for d in b["deltas"]},
                         {("avoid-v1", "idle"), ("avoid-v1", "simple-move")})
        self.assertTrue(b["interleaving"]["alternating"])
        self.assertTrue(any("탐색 비교" in n for n in b["notes"]))
        pol = {p["name"]: p for p in b["policies"]}
        self.assertEqual(pol["avoid-v1"]["started"], 6)  # 누락 에피소드 포함
        self.assertEqual(pol["avoid-v1"]["survive_all"]["n"], 6)
        self.assertEqual(pol["idle"]["by_status"]["timeout"], 1)

    def test_different_conditions_are_not_compared(self):
        a = fb.build_policy_run(self.tmp, "20261029T000000Z-aaaaaa", ("idle", "0"), [{"t": "survive"}], shot_inverted=1)
        b = fb.build_policy_run(self.tmp, "20261029T000000Z-bbbbbb", ("avoid-v1", "0"), [{"t": "survive"}], shot_inverted=0)
        cmp = compare.compare([a, b])
        self.assertEqual(len(cmp["buckets"]), 2)
        self.assertTrue(cmp["warnings"])
        for bk in cmp["buckets"]:
            self.assertEqual(bk["deltas"], [])

    def test_blocked_order_is_flagged(self):
        a = fb.build_policy_run(self.tmp, "20261029T000000Z-aaaaaa", ("idle", "0"), [{"t": "survive"}] * 3, nslots=1, slot=0)
        b = fb.build_policy_run(self.tmp, "20261029T000000Z-bbbbbb", ("avoid-v1", "0"), [{"t": "survive"}] * 3, nslots=1, slot=10)
        cmp = compare.compare([a, b])
        il = cmp["buckets"][0]["interleaving"]
        self.assertFalse(il["alternating"])
        self.assertTrue(any("번갈아" in n for n in cmp["buckets"][0]["notes"]))


class PlanAndCliTests(Base):
    def setUp(self):
        super().setUp()
        with open(os.path.join(ROOT, "evaluation", "configs", "eval-set-v0.json"), encoding="utf-8") as f:
            self.es = json.load(f)

    def test_plan_counts_and_interleave(self):
        rows = plan.expand(self.es, "seeded", include_holdout=True)
        dev = [r for r in rows if r["purpose"] != "holdout:다른 스펠" and not r["purpose"].startswith("holdout")]
        self.assertEqual(len(dev), 20 * 3 + 5 * 3)
        self.assertEqual(len([r for r in rows if r["purpose"].startswith("holdout")]), 6)
        self.assertEqual([r["policy"] for r in rows[:6]], ["idle", "simple-move", "avoid-v1"] * 2)
        self.assertEqual(len({r["seed"] for r in rows if r["purpose"] == "dev_seeded"}), 20)
        probe = [r for r in rows if r["purpose"] == "determinism_probe"]
        self.assertEqual(len({r["seed"] for r in probe}), 1)
        self.assertEqual(len(plan.expand(self.es, "uncontrolled")), 90)
        self.assertTrue(all(r["seed"] is None for r in plan.expand(self.es, "uncontrolled")))

    def test_cli_evaluate_writes_outputs_without_touching_inputs(self):
        runs = fb.build_sample(self.tmp)
        d = runs["idle"]
        before = hash_tree(d)
        out = os.path.join(self.tmp, "out")
        self.assertEqual(cli.main(["evaluate", d, "--out", out]), 0)
        self.assertEqual(hash_tree(d), before)
        for name in ("evaluation.json", "episodes.csv", "groups.csv", "report.md"):
            self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
        with open(os.path.join(out, "episodes.csv"), encoding="utf-8") as f:
            self.assertEqual(len(f.read().strip().splitlines()), 1 + 6)
        self.assertEqual(cli.main(["validate", "evaluation", os.path.join(out, "evaluation.json")]), 0)

    def test_cli_regenerates_identical_summary(self):
        d = fb.build_sample(self.tmp)["simple-move"]
        outs = []
        for i in range(2):
            o = os.path.join(self.tmp, f"o{i}")
            cli.main(["evaluate", d, "--out", o])
            with open(os.path.join(o, "evaluation.json"), encoding="utf-8") as fh:
                res = json.load(fh)
            res.pop("generated_at")
            outs.append(res)
        self.assertEqual(outs[0], outs[1])

    def test_cli_bad_input_exit_codes(self):
        self.assertEqual(cli.main(["evaluate", os.path.join(self.tmp, "nope")]), 2)
        self.assertEqual(cli.main(["plan", "--set", os.path.join(self.tmp, "nope.json")]), 2)

    def test_cli_compare(self):
        runs = fb.build_sample(self.tmp)
        out = os.path.join(self.tmp, "cmp")
        self.assertEqual(cli.main(["compare", *runs.values(), "--out", out]), 0)
        self.assertTrue(os.path.isfile(os.path.join(out, "comparison.md")))


if __name__ == "__main__":
    unittest.main()
