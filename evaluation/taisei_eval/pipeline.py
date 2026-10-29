"""run 폴더 하나를 평가하고 JSON/CSV/마크다운을 쓴다."""
import csv
import datetime
import json
import os

from . import VERSION
from . import constants as C
from . import failure, judge, loader, schema_lite, summarize

ASSUMPTIONS = [
    "A1 실행 계약 v1 미확정: run.json·episodes/NNNN.json은 #20 v0.1 5절을 가정한 형식이다(schemas/run.schema.json, episode.schema.json).",
    "A2 trace(episodes/NNNN.trace.jsonl)는 호스트가 논리 프레임마다 브리지 관측의 부분집합과 액션·판단 시간을 합쳐 쓴다고 가정한다(schemas/trace.schema.json).",
    "A3 브리지 계약 v1(docs/ai/CONTRACT.md, feat/ai-bridge fd63e57)의 phase 전이·카운터·cheat_flags·overflow·act_* 의미를 그대로 쓴다.",
    "A4 판정 규칙의 일시정지·재시작 정상 경계 해석은 실행기와 합의 전이다(docs/ai/EVALUATION.md 6절).",
]


def _support(records):
    sup = {
        "reproducibility": "not_verified",
        "frame_step": "unsupported",
        "browser_roundtrip_latency": "not_measured",
        "seed_control": "supported" if any(r["seed"].get("control") == "set" for r in records) else "not_measured",
    }
    if any(r.get("build_flavor") == "developer" for r in records):
        sup["rules_preservation_developer_build"] = "not_verified"
    return sup


def evaluate_run(run_dir, window_frames=None):
    run_json, run_errors, loaded, requested = loader.load_run(run_dir)
    indices = set(loaded)
    if requested is not None:
        indices |= set(range(1, requested + 1))
    items = []
    for idx in sorted(indices):
        le = loaded.get(idx)
        if le is None:
            le = loader.LoadedEpisode(idx)
            le.missing = True
        rec, internal = judge.evaluate_loaded(le, run_json)
        if window_frames is None:
            ep = le.episode if isinstance(le.episode, dict) else {}
            win = ((ep.get("config") or {}).get("pre_hit_window_frames")) or C.DEFAULT_PRE_HIT_WINDOW
        else:
            win = window_frames
        items.append((rec, internal, win))

    failures = []
    for rec, internal, win in items:
        fl = failure.collect(rec, internal.get("trace") or [], win)
        for f in fl:
            f["evidence"]["failure_index"] = len(failures)
            failures.append(f)
        if fl:
            rec["evidence"]["failure_explanations"] = len(fl)

    records = [r for r, _, _ in items]
    groups = summarize.build_groups([(r, i) for r, i, _ in items])
    rj = run_json or {}
    out = {
        "schema": "taisei-ai-evaluation/1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": {"name": "taisei_eval", "version": VERSION},
        "source": {
            "run_dir": os.path.abspath(run_dir), "run_id": rj.get("run_id"), "experiment_id": rj.get("experiment_id"),
            "runner_exit_code": rj.get("exit_code"), "requested_episodes": requested,
            "found_episodes": len(loaded), "requested_known": requested is not None,
            "run_json_problems": run_errors,
        },
        "support": _support(records),
        "assumptions": ASSUMPTIONS,
        "episodes": records,
        "groups": groups,
        "failures": failures,
    }
    return out


def write_outputs(result, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    errs = schema_lite.validate(result, "evaluation.schema.json")
    paths = {}
    p = os.path.join(out_dir, "evaluation.json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    paths["evaluation.json"] = p

    p = os.path.join(out_dir, "episodes.csv")
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(EP_COLS)
        for r in result["episodes"]:
            w.writerow(ep_row(r))
    paths["episodes.csv"] = p

    p = os.path.join(out_dir, "groups.csv")
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(GROUP_COLS)
        for g in result["groups"]:
            w.writerow(group_row(g))
    paths["groups.csv"] = p

    p = os.path.join(out_dir, "report.md")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_report(result))
    paths["report.md"] = p
    return paths, errs


EP_COLS = ["run_id", "episode_index", "policy", "policy_version", "scenario_kind", "scenario_id", "difficulty", "character", "shot",
           "build_flavor", "shot_inverted", "seed_control", "seed_requested", "seed_actual",
           "status", "reason", "status_by_runner", "evaluable", "survived", "first_death_frame", "pattern_captured", "stage_cleared",
           "frames_survived", "seconds_survived", "hits", "deaths", "deathbombs", "uncounted_deaths", "bombs_policy", "continues",
           "decision_p50_ms", "decision_p95_ms", "decision_max_ms", "over_policy_budget", "over_frame_budget",
           "input_lag_p50", "input_lag_max", "sim_fps_mean", "sim_below_60_ratio",
           "observation_complete", "overflow_frames", "act_stale", "act_dup", "act_missing", "counters_consistent", "notes"]


def _g(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def ep_row(r):
    m = r["metrics"] or {}
    res = r["result"] or {}
    q = r["quality"]
    sync = q["action_sync"]
    return [
        r["ref"]["run_id"], r["ref"]["episode_index"], r["policy"].get("name"), r["policy"].get("version"),
        r["scenario"].get("kind"), r["scenario"].get("id"), r["scenario"].get("difficulty"), r["scenario"].get("character"), r["scenario"].get("shot"),
        r.get("build_flavor"), r.get("shot_inverted"), r["seed"].get("control"), r["seed"].get("requested"), r["seed"].get("actual"),
        r["run"]["status"], r["run"]["reason"], r["run"]["status_by_runner"]["status"], r["run"]["evaluable"],
        res.get("survived"), res.get("first_death_frame"), res.get("pattern_captured"), res.get("stage_cleared"),
        m.get("frames_survived"), m.get("seconds_survived"), m.get("hits"), m.get("deaths"), m.get("deathbombs"),
        m.get("uncounted_deaths"), m.get("bombs_policy"), m.get("continues"),
        _g(m, "decision_ms", "p50"), _g(m, "decision_ms", "p95"), _g(m, "decision_ms", "max"),
        _g(m, "decision_ms", "over_policy_budget"), _g(m, "decision_ms", "over_frame_budget"),
        _g(m, "input_lag_frames", "p50"), _g(m, "input_lag_frames", "max"), _g(m, "sim_fps", "mean"), _g(m, "sim_fps", "below_60_ratio"),
        q["observation_complete"], q["overflow_frames"], sync.get("stale"), sync.get("dup"), sync.get("missing"),
        _g(q, "counters_check", "consistent"), " | ".join(r["run"].get("notes", []))[:300],
    ]


GROUP_COLS = ["policy", "policy_version", "scenario_kind", "scenario_id", "difficulty", "character", "shot", "build_flavor", "shot_inverted",
              "seed_design", "comparison_class", "started", "evaluable", "completed", "timeout", "aborted", "error", "unsupported",
              "invalid", "missing", "obs_complete", "obs_incomplete",
              "survive_all_k", "survive_all_rate", "survive_all_lo", "survive_all_hi",
              "survive_eval_k", "survive_eval_n", "survive_eval_rate", "survive_eval_lo", "survive_eval_hi",
              "goal_all_rate", "goal_eval_rate", "frames_survived_p50", "hits_mean", "decision_p50_ms", "decision_p95_ms",
              "decision_max_ms", "sim_fps_mean"]


def group_row(g):
    c, r, m = g["counts"], g["rates"], g["metrics"]
    s = g["condition"]["scenario"] or {}
    st = c["by_status"]
    goal_all = r.get("capture_all") or r.get("clear_all")
    goal_ev = r.get("capture_evaluable") or r.get("clear_evaluable")
    sa, se = r["survive_all"], r["survive_evaluable"]
    return [
        g["policy"].get("name"), g["policy"].get("version"), s.get("kind"), s.get("id"), s.get("difficulty"), s.get("character"), s.get("shot"),
        g["condition"].get("build_flavor"), g["condition"].get("shot_inverted"), g["seed_design"], g["comparison_class"],
        c["started"], c["evaluable"], *[st.get(k, 0) for k in ("completed", "timeout", "aborted", "error", "unsupported", "invalid", "missing")],
        c["observation_complete"], c["observation_incomplete"],
        sa["k"], sa["rate"], (sa["wilson95"] or [None, None])[0], (sa["wilson95"] or [None, None])[1],
        se["k"], se["n"], se["rate"], (se["wilson95"] or [None, None])[0], (se["wilson95"] or [None, None])[1],
        goal_all["rate"] if goal_all else None, goal_ev["rate"] if goal_ev else None,
        m["frames_survived"]["p50"], m["hits"]["mean"],
        _g(m, "decision_ms_pooled", "p50"), _g(m, "decision_ms_pooled", "p95"), _g(m, "decision_ms_pooled", "max"),
        _g(m, "sim_fps", "mean_of_means"),
    ]


def pct(r):
    if not r or r["rate"] is None:
        return "-"
    lo, hi = r["wilson95"]
    return f"{r['k']}/{r['n']} = {r['rate'] * 100:.1f}% [{lo * 100:.0f}–{hi * 100:.0f}]"


def render_report(res):
    src = res["source"]
    L = ["# AI 평가 리포트", "",
         f"- run: `{src.get('run_id')}` / 실험: `{src.get('experiment_id')}` / 실행기 종료 코드: {src.get('runner_exit_code')}",
         f"- 요청 에피소드: {src['requested_episodes'] if src['requested_known'] else '알 수 없음(run.json 없음)'}, 읽은 파일: {src['found_episodes']}",
         f"- 도구: {res['tool']['name']} {res['tool']['version']} · 생성: {res['generated_at']}", ""]
    if src.get("run_json_problems"):
        L += ["> run.json 문제: " + "; ".join(src["run_json_problems"]), ""]
    L += ["## 그룹 요약 (정책 × 조건)", "",
          "성공률 형식: `성공/분모 = 비율 [Wilson 95% 하한–상한]`. `전체`는 시작한 모든 에피소드가 분모, `평가 가능`은 평가 가능한 것만 분모.", ""]
    for g in res["groups"]:
        s = g["condition"]["scenario"] or {}
        c, r = g["counts"], g["rates"]
        L += [f"### {g['policy'].get('name')} {g['policy'].get('version') or ''} — {s.get('kind')} {s.get('id')} {s.get('difficulty') or ''}",
              "",
              f"- 설계: `{g['seed_design']}` ({g['comparison_class']}) · 빌드 `{g['condition'].get('build_flavor')}` · shot_inverted `{g['condition'].get('shot_inverted')}` · 재현성 `{g['reproducibility']}`",
              f"- 시작 {c['started']} · 평가 가능 {c['evaluable']} · 상태별 {_fmt(c['by_status'])}",
              f"- 생존율(전체) {pct(r['survive_all'])}",
              f"- 생존율(평가 가능) {pct(r['survive_evaluable'])}",
              f"  - 관측 완전 {pct(r['survive_evaluable_complete_obs'])} / 불완전 {pct(r['survive_evaluable_incomplete_obs'])}"]
        if r.get("capture_all"):
            L += [f"- 캡처율(전체) {pct(r['capture_all'])} · (평가 가능) {pct(r['capture_evaluable'])}"]
        if r.get("clear_all"):
            L += [f"- 클리어율(전체) {pct(r['clear_all'])} · (평가 가능) {pct(r['clear_evaluable'])}"]
        m = g["metrics"]
        d = m.get("decision_ms_pooled")
        L += [f"- 생존 프레임 p50 {m['frames_survived']['p50']} (평균 {m['frames_survived']['mean']}) · 피격 평균 {m['hits']['mean']} · 사망 평균 {m['deaths']['mean']}",
              f"- 판단 지연 ms: " + (f"p50 {d['p50']} / p95 {d['p95']} / max {d['max']} (4ms 초과 {d['over_policy_budget']}, 16.7ms 초과 {d['over_frame_budget']})" if d else "측정 없음"),
              f"- 실행 속도: " + (f"평균 {m['sim_fps']['mean_of_means']} fps, 느린 창 비율 {m['sim_fps']['below_60_ratio_mean']}" if m.get("sim_fps") else "측정 없음"),
              ]
        if g.get("same_seed_agreement"):
            a = g["same_seed_agreement"]
            L += [f"- 같은 시드 반복 일치(관측): {a['agreeing']}/{a['seeds_with_repeats']} 시드 — {a['note']}"]
        if g["unsupported_items"]:
            L += [f"- 지원·검증 안 됨: {', '.join(g['unsupported_items'])}"]
        L += ["- 주의:"] + [f"  - {x}" for x in g["caveats"]] + [""]

    L += ["## 에피소드 상태", "", "| run | # | 정책 | 상태 | 사유 | 실행기 판정 | 생존 | 피격 | 사망 | 생존 프레임 | 관측 | 비고 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in res["episodes"]:
        m, rs = e["metrics"] or {}, e["result"] or {}
        L.append("| {} | {} | {} | {} | {} | {}{} | {} | {} | {} | {} | {} | {} |".format(
            (e["ref"]["run_id"] or "-")[-6:], e["ref"]["episode_index"], e["policy"].get("name") or "-", e["run"]["status"], e["run"]["reason"],
            e["run"]["status_by_runner"]["status"] or "-", " (변경)" if e["run"]["status_by_runner"]["overridden"] else "",
            _b(rs.get("survived")), m.get("hits", "-"), m.get("deaths", "-"), m.get("frames_survived", "-"),
            "완전" if e["quality"]["observation_complete"] else "불완전", "; ".join(e["run"].get("notes", []))[:80].replace("|", "/")))
    L += [""]

    L += ["## 충돌 직전 구간 (실패 설명)", ""]
    if not res["failures"]:
        L += ["피격 이벤트가 있는 평가 가능 에피소드가 없다.", ""]
    for f in res["failures"][:20]:
        nb = f.get("nearest_bullet")
        acts = ", ".join(f"{a['hold']}×{a['frames']}" for a in f["actions"][-6:])
        L += [f"- `{f['ref']['run_id']}` #{f['ref']['episode_index']} {f['policy']}: 프레임 {f['event']['frame']} {f['event']['type']} · "
              f"구간 {f['window']['start_frame']}–{f['window']['end_frame']} · 최근 입력 {acts} · "
              + (f"가장 가까운 탄 거리 {nb['distance']} (프레임 {nb['frame']}) · " if nb else "") + f"태그 {', '.join(f['tags'])} · trace `{f['evidence'].get('trace')}`"]
    if len(res["failures"]) > 20:
        L += [f"- (그 밖에 {len(res['failures']) - 20}건은 evaluation.json의 failures에 있다)"]
    L += ["", "태그는 trace를 열어 볼 위치를 알려 주는 단서이며 원인 증명이 아니다.", ""]

    L += ["## 지원·검증 현황", ""] + [f"- {k}: `{v}`" for k, v in res["support"].items()] + ["", "## 가정", ""] + [f"- {a}" for a in res["assumptions"]] + [""]
    return "\n".join(L)


def _fmt(d):
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items()))


def _b(v):
    return "-" if v is None else ("O" if v else "X")
