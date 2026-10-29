"""에피소드 평가 → 그룹(정책×조건) 요약.

성공률 분모는 두 가지를 항상 같이 낸다.
- *_all: 시작한 모든 에피소드(누락·실패·시간 초과 포함). 실행 안정성까지 포함한 실제 성능.
- *_evaluable: run.evaluable=true인 에피소드. 정책 자체의 성능.
"""
import json
from collections import Counter, OrderedDict

from . import stats

MIN_SAMPLE = 30


def condition_of(rec):
    lim = rec.get("limits") or {}
    return OrderedDict([
        ("scenario", rec["scenario"]),
        ("build_flavor", rec.get("build_flavor")),
        ("shot_inverted", rec.get("shot_inverted")),
        ("max_frames", lim.get("max_frames")),
        ("wall_timeout_s", lim.get("wall_timeout_s")),
    ])


def condition_key(cond):
    return json.dumps(cond, sort_keys=True, ensure_ascii=False)


def seed_design(recs):
    """에피소드들의 시드 설정으로 평가 설계를 분류한다."""
    controls = {r["seed"].get("control") for r in recs}
    if controls <= {"random", None}:
        return "uncontrolled", {"distinct_seeds": None, "episodes_per_seed": None}
    if controls == {"replay"}:
        return "replay", {"distinct_seeds": None, "episodes_per_seed": None}
    if controls <= {"set", "unsupported"}:
        requested = [r["seed"].get("requested") for r in recs if r["seed"].get("requested") is not None]
        if requested:
            c = Counter(str(x) for x in requested)
            per = sorted(c.values())
            info = {"distinct_seeds": len(c), "episodes_per_seed": {"min": per[0], "max": per[-1]}}
            if len(c) == 1:
                return ("fixed_seed_repeat" if len(requested) > 1 else "single_seed"), info
            return "multi_seed", info
    return "mixed", {"distinct_seeds": None, "episodes_per_seed": None}


def _signature(r):
    ev = tuple((e["type"], e.get("frame")) for e in r["events"] if e["type"] in ("hit", "death", "deathbomb", "bomb"))
    res = r["result"] or {}
    return (res.get("survived"), res.get("first_death_frame"), ev)


def same_seed_agreement(recs):
    by_seed = {}
    for r in recs:
        if r["run"]["evaluable"] and r["seed"].get("control") == "set" and r["seed"].get("requested") is not None:
            by_seed.setdefault(str(r["seed"]["requested"]), []).append(_signature(r))
    rep = {s: sigs for s, sigs in by_seed.items() if len(sigs) >= 2}
    if not rep:
        return None
    agree = sum(1 for sigs in rep.values() if len(set(sigs)) == 1)
    return {"seeds_with_repeats": len(rep), "agreeing": agree, "disagreeing": len(rep) - agree,
            "note": "관측된 일치 여부일 뿐 재현 검증(상태 해시·desync 검사)이 아니다"}


def build_groups(items):
    """items: [(평가 레코드, 내부)] → 그룹 목록."""
    buckets = OrderedDict()
    for rec, internal in items:
        cond = condition_of(rec)
        pol = rec["policy"]
        key = json.dumps([pol.get("name"), pol.get("version"), cond], sort_keys=True, ensure_ascii=False)
        buckets.setdefault(key, {"cond": cond, "policy": pol, "items": []})["items"].append((rec, internal))
    return [_group(k, b) for k, b in buckets.items()]


def _group(key, b):
    recs = [r for r, _ in b["items"]]
    internals = [i for _, i in b["items"]]
    ev = [(r, i) for r, i in b["items"] if r["run"]["evaluable"]]
    n_all, n_ev = len(recs), len(ev)
    kind = (b["cond"]["scenario"] or {}).get("kind")
    by_status = Counter(r["run"]["status"] for r in recs)
    by_reason = Counter(f"{r['run']['status']}/{r['run']['reason']}" for r in recs)
    complete = [r for r, _ in ev if r["quality"]["observation_complete"]]
    incomplete = [r for r, _ in ev if not r["quality"]["observation_complete"]]
    surv = lambda rs: sum(1 for r in rs if r["result"]["survived"])  # noqa: E731

    rates = {
        "survive_all": stats.rate(surv([r for r, _ in ev]), n_all),
        "survive_evaluable": stats.rate(surv([r for r, _ in ev]), n_ev),
        "survive_evaluable_complete_obs": stats.rate(surv(complete), len(complete)),
        "survive_evaluable_incomplete_obs": stats.rate(surv(incomplete), len(incomplete)),
        "capture_all": None, "capture_evaluable": None, "clear_all": None, "clear_evaluable": None,
    }
    if kind == "spell":
        k = sum(1 for r, _ in ev if r["result"]["pattern_captured"])
        rates["capture_all"], rates["capture_evaluable"] = stats.rate(k, n_all), stats.rate(k, n_ev)
    elif kind == "stage":
        k = sum(1 for r, _ in ev if r["result"]["stage_cleared"])
        rates["clear_all"], rates["clear_evaluable"] = stats.rate(k, n_all), stats.rate(k, n_ev)

    mets = [r["metrics"] for r, _ in ev if r["metrics"]]
    samples = [s for r, i in ev for s in i.get("decision_samples", [])]
    lag_p50 = [m["input_lag_frames"]["p50"] for m in mets if m.get("input_lag_frames")]
    lag_max = [m["input_lag_frames"]["max"] for m in mets if m.get("input_lag_frames")]
    fps = [m["sim_fps"] for m in mets if m.get("sim_fps")]
    below = [f["below_60_ratio"] for f in fps if f.get("below_60_ratio") is not None]
    dec = None
    if samples:
        from . import constants as C
        dec = {"n": len(samples), "p50": round(stats.percentile(samples, 50), 3), "p95": round(stats.percentile(samples, 95), 3), "max": round(max(samples), 3),
               "over_policy_budget": sum(1 for v in samples if v > C.POLICY_BUDGET_MS),
               "over_frame_budget": sum(1 for v in samples if v > C.FRAME_BUDGET_MS)}
    metrics = {
        "frames_survived": stats.dist([m["frames_survived"] for m in mets]),
        "hits": stats.dist([m["hits"] for m in mets]),
        "deaths": stats.dist([m["deaths"] for m in mets]),
        "bombs": stats.dist([m["bombs_policy"] + m["bombs_deathbomb"] for m in mets]),
        "decision_ms_pooled": dec,
        "input_lag_frames": ({"episodes": len(lag_p50), "median_of_p50": stats.percentile(lag_p50, 50), "max": max(lag_max)} if lag_p50 else None),
        "sim_fps": ({"episodes": len(fps), "mean_of_means": round(stats.mean([f["mean"] for f in fps]), 2),
                     "below_60_ratio_mean": (round(stats.mean(below), 4) if below else None)} if fps else None),
    }

    design, seed_info = seed_design(recs)
    caveats = ["Wilson 95% 구간은 에피소드가 서로 독립이라는 가정에서만 맞는다. 같은 브라우저 세션을 이어 쓰면 깨질 수 있다."]
    if design in ("uncontrolled", "mixed"):
        caveats.append("시드를 통제하지 않은 탐색 비교다. 정책 간 우열을 확정하는 근거로 쓰지 않는다.")
    if n_all < MIN_SAMPLE:
        caveats.append(f"시작한 에피소드가 {n_all}개로 {MIN_SAMPLE}개 미만이다(소표본).")
    if b["cond"].get("build_flavor") == "developer" or any(r.get("rules_preserved") == "unverified" for r in recs):
        caveats.append("개발자 빌드: 원본 규칙 보존이 검증되지 않았다(rules_preserved=unverified). 원래 규칙의 클리어 증거로 쓰지 않는다.")
    if incomplete:
        caveats.append(f"관측 불완전(overflow·프레임 누락) 에피소드 {len(incomplete)}개: 성공해도 안전 판단 증거로 쓰지 않는다.")
    nonev = n_all - n_ev
    if nonev:
        caveats.append(f"평가 불가 에피소드 {nonev}개는 *_all 분모에 들어 있다.")

    unsupported = ["reproducibility"]
    if mets and not dec:
        unsupported.append("decision_ms")
    if mets and not lag_p50:
        unsupported.append("input_lag_frames")
    if mets and not fps:
        unsupported.append("sim_fps")

    starts = sorted(r["started_at"] for r in recs if r.get("started_at"))
    return {
        "key": key, "policy": b["policy"], "condition": b["cond"], "condition_key": condition_key(b["cond"]),
        "seed_design": design, "seed_info": seed_info,
        "comparison_class": "controlled" if design in ("single_seed", "fixed_seed_repeat", "multi_seed", "replay") else "exploratory",
        "reproducibility": "not_verified",
        "same_seed_agreement": same_seed_agreement(recs),
        "counts": {"started": n_all, "evaluable": n_ev, "by_status": dict(by_status), "by_reason": dict(by_reason),
                   "observation_complete": len(complete), "observation_incomplete": len(incomplete)},
        "rates": rates, "metrics": metrics, "caveats": caveats, "unsupported_items": unsupported, "starts": starts,
    }
