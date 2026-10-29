"""기준선(정지·단순 이동) 대 정책 비교 리포트.

같은 조건(condition_key: 시나리오·빌드·shot_inverted·한도)의 그룹끼리만 비교한다.
조건이 하나라도 다르면 비교하지 않고 이유를 적는다. 시드를 통제하지 않은 비교는 `exploratory`로 표시한다.
"""
import csv
import json
import os
from collections import OrderedDict

from . import VERSION, pipeline, schema_lite

DEFAULT_BASELINES = ("idle", "simple-move")


def load_groups(paths):
    """각 경로는 evaluation.json, 그것을 가진 폴더, 또는 평가 전 run 폴더(즉석 평가)."""
    out = []
    for p in paths:
        if os.path.isfile(p):
            ev_path = p
        elif os.path.isfile(os.path.join(p, "evaluation", "evaluation.json")):
            ev_path = os.path.join(p, "evaluation", "evaluation.json")
        elif os.path.isfile(os.path.join(p, "evaluation.json")):
            ev_path = os.path.join(p, "evaluation.json")
        else:
            ev_path = None
        if ev_path:
            with open(ev_path, "r", encoding="utf-8") as f:
                res = json.load(f)
        else:
            res = pipeline.evaluate_run(p)
        for g in res["groups"]:
            out.append((p, res["source"].get("run_id"), g))
    return out


def _scenario_key(g):
    return json.dumps(g["condition"].get("scenario"), sort_keys=True, ensure_ascii=False)


def compare(paths, baselines=DEFAULT_BASELINES):
    entries = load_groups(paths)
    buckets = OrderedDict()
    for src, run_id, g in entries:
        buckets.setdefault(g["condition_key"], []).append((src, run_id, g))

    out_buckets, warnings = [], []
    by_scenario = {}
    for ck, items in buckets.items():
        by_scenario.setdefault(_scenario_key(items[0][2]), []).append(ck)
    for sk, cks in by_scenario.items():
        if len(cks) > 1:
            warnings.append(f"시나리오는 같지만 빌드·shot_inverted·한도가 다른 조건 {len(cks)}개가 있어 서로 비교하지 않았다: {sk}")

    for ck, items in buckets.items():
        cond = items[0][2]["condition"]
        pols = []
        for src, run_id, g in items:
            r, c = g["rates"], g["counts"]
            pols.append({
                "name": g["policy"].get("name"), "version": g["policy"].get("version"), "source": src, "run_id": run_id,
                "seed_design": g["seed_design"], "comparison_class": g["comparison_class"],
                "started": c["started"], "evaluable": c["evaluable"], "by_status": c["by_status"],
                "survive_all": r["survive_all"], "survive_evaluable": r["survive_evaluable"],
                "goal_all": r.get("capture_all") or r.get("clear_all"),
                "goal_evaluable": r.get("capture_evaluable") or r.get("clear_evaluable"),
                "frames_survived_p50": g["metrics"]["frames_survived"]["p50"], "hits_mean": g["metrics"]["hits"]["mean"],
                "decision_ms": g["metrics"].get("decision_ms_pooled"), "sim_fps": g["metrics"].get("sim_fps"),
                "observation_incomplete": c["observation_incomplete"], "caveats": g["caveats"], "starts": g.get("starts", []),
            })
        present = {p["name"] for p in pols}
        base = [p for p in pols if p["name"] in baselines]
        missing_base = [b for b in baselines if b not in present]
        classes = {p["comparison_class"] for p in pols}
        designs = {p["seed_design"] for p in pols}
        cls = "controlled" if classes == {"controlled"} and len(designs) == 1 else "exploratory"
        notes = []
        if cls == "exploratory":
            notes.append("시드를 통제하지 않았거나 정책 간 시드 설계가 다르다. 탐색 비교이며 우열을 확정하는 근거로 쓰지 않는다.")
        if missing_base:
            notes.append("기준선이 없다: " + ", ".join(missing_base))
        if any(p["started"] < 30 for p in pols):
            notes.append("시작한 에피소드가 30개 미만인 정책이 있다(소표본).")
        deltas = []
        for p in pols:
            if p["name"] in baselines:
                continue
            for b in base:
                deltas.append({"policy": p["name"], "vs": b["name"],
                               "survive_all_diff": _diff(p["survive_all"], b["survive_all"]),
                               "survive_evaluable_diff": _diff(p["survive_evaluable"], b["survive_evaluable"]),
                               "separation_all": _separation(p["survive_all"], b["survive_all"])})
        seq = sorted((s, p["name"]) for p in pols for s in p["starts"])
        max_run, cur, prev = 0, 0, None
        for _, n in seq:
            cur = cur + 1 if n == prev else 1
            max_run, prev = max(max_run, cur), n
        inter = {"episodes_with_time": len(seq), "max_consecutive_same_policy": max_run or None,
                 "alternating": (max_run <= 1) if seq else None}
        if seq and max_run > 1 and len({n for _, n in seq}) > 1:
            notes.append(f"정책 실행 순서가 번갈아 있지 않다(같은 정책 최대 {max_run}회 연속). 시간대·발열·브라우저 상태 변화가 한 정책에 몰릴 수 있다.")
        out_buckets.append({"condition": cond, "condition_key": ck, "comparison_class": cls, "policies": pols,
                            "deltas": deltas, "interleaving": inter, "notes": notes, "reproducibility": "not_verified"})
    return {"schema": "taisei-ai-comparison/1", "tool": {"name": "taisei_eval", "version": VERSION},
            "baselines": list(baselines), "warnings": warnings, "buckets": out_buckets}


def _diff(a, b):
    if a is None or b is None or a["rate"] is None or b["rate"] is None:
        return None
    return round(a["rate"] - b["rate"], 4)


def _separation(a, b):
    if not a or not b or not a.get("wilson95") or not b.get("wilson95"):
        return None
    if a["wilson95"][0] > b["wilson95"][1]:
        return "higher_intervals_separate"
    if a["wilson95"][1] < b["wilson95"][0]:
        return "lower_intervals_separate"
    return "intervals_overlap"


def write_outputs(cmp, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    errs = schema_lite.validate(cmp, "comparison.schema.json")
    p1 = os.path.join(out_dir, "comparison.json")
    with open(p1, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cmp, f, ensure_ascii=False, indent=2)
        f.write("\n")
    p2 = os.path.join(out_dir, "comparison.csv")
    with open(p2, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["scenario_id", "difficulty", "build_flavor", "shot_inverted", "class", "policy", "version", "seed_design",
                    "started", "evaluable", "survive_all", "survive_all_lo", "survive_all_hi", "survive_eval",
                    "frames_survived_p50", "hits_mean", "decision_p95_ms", "obs_incomplete"])
        for b in cmp["buckets"]:
            s = b["condition"]["scenario"] or {}
            for p in b["policies"]:
                sa = p["survive_all"]
                w.writerow([s.get("id"), s.get("difficulty"), b["condition"].get("build_flavor"), b["condition"].get("shot_inverted"),
                            b["comparison_class"], p["name"], p["version"], p["seed_design"], p["started"], p["evaluable"],
                            sa["rate"], (sa["wilson95"] or [None, None])[0], (sa["wilson95"] or [None, None])[1], p["survive_evaluable"]["rate"],
                            p["frames_survived_p50"], p["hits_mean"], (p["decision_ms"] or {}).get("p95"), p["observation_incomplete"]])
    p3 = os.path.join(out_dir, "comparison.md")
    with open(p3, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(cmp))
    return [p1, p2, p3], errs


def render(cmp):
    L = ["# 기준선 대 정책 비교", "", f"기준선: {', '.join(cmp['baselines'])}", ""]
    for w in cmp["warnings"]:
        L += [f"> 경고: {w}", ""]
    for b in cmp["buckets"]:
        s = b["condition"]["scenario"] or {}
        L += [f"## {s.get('kind')} {s.get('id')} {s.get('difficulty') or ''} · {s.get('character') or ''} {s.get('shot') or ''}",
              f"빌드 `{b['condition'].get('build_flavor')}` · shot_inverted `{b['condition'].get('shot_inverted')}` · max_frames `{b['condition'].get('max_frames')}` · "
              f"분류 **{b['comparison_class']}** · 재현성 `{b['reproducibility']}`", "",
              "| 정책 | 시드 설계 | 시작 | 평가 가능 | 생존율(전체) | 생존율(평가 가능) | 생존 프레임 p50 | 피격 평균 | 판단 p95 ms | 관측 불완전 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for p in b["policies"]:
            d = p["decision_ms"]
            L.append(f"| {p['name']} {p['version'] or ''} | {p['seed_design']} | {p['started']} | {p['evaluable']} | {pipeline.pct(p['survive_all'])} | "
                     f"{pipeline.pct(p['survive_evaluable'])} | {p['frames_survived_p50']} | {p['hits_mean']} | {d['p95'] if d else '-'} | {p['observation_incomplete']} |")
        L.append("")
        if b["deltas"]:
            L += ["| 정책 | 기준선 | 생존율 차(전체) | 생존율 차(평가 가능) | 구간 분리 |", "|---|---|---|---|---|"]
            for d in b["deltas"]:
                L.append(f"| {d['policy']} | {d['vs']} | {_pp(d['survive_all_diff'])} | {_pp(d['survive_evaluable_diff'])} | {d['separation_all']} |")
            L.append("")
        il = b["interleaving"]
        L += [f"실행 순서: 시각이 있는 에피소드 {il['episodes_with_time']}개, 같은 정책 최대 연속 {il['max_consecutive_same_policy']}, 번갈아 실행 {il['alternating']}", ""]
        for n in b["notes"]:
            L.append(f"- 주의: {n}")
        L.append("")
    return "\n".join(L)


def _pp(x):
    return "-" if x is None else f"{x * 100:+.1f}%p"
