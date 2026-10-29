"""충돌 직전의 관측·액션 구간 추출과 실패 설명 태그.

태그는 사람이 trace를 열어 볼 위치를 알려 주는 단서이며 원인 증명이 아니다.
"""
import math

from . import constants as C


def hold_text(h):
    if h is None:
        return None
    names = [n for bit, n in C.HOLD_NAMES if h & bit]
    return "+".join(names) if names else "-"


def _rle(trace):
    out = []
    for r in trace:
        h = r.get("hold_applied")
        if out and out[-1]["_h"] == h:
            out[-1]["frames"] += 1
        else:
            out.append({"_h": h, "hold": hold_text(h), "from_frame": r["frame"], "frames": 1})
    for o in out:
        o.pop("_h")
    return out


def _nearest(window):
    best = None
    for r in window:
        for b in (r.get("near") or []):
            d = math.hypot(r.get("x", 0) - b[1], r.get("y", 0) - b[2]) - b[3]
            if best is None or d < best["distance"]:
                best = {"frame": r["frame"], "bullet_id": int(b[0]), "distance": round(d, 2), "bullet_xy": [b[1], b[2]]}
    return best


def explain(record, trace, event, window_frames):
    """event(hit 또는 death) 직전 window_frames 프레임의 증거를 모은다."""
    f = event["frame"]
    window = [r for r in trace if f - window_frames <= r["frame"] <= f]
    if not window:
        return None
    first, last = window[0], window[-1]
    tags = []
    if any(r["overflow"] for r in window):
        tags.append("observation_incomplete")
    sync0, sync1 = first, last
    for k in ("act_missing", "act_stale", "act_dup"):
        if (sync1.get(k) or 0) > (sync0.get(k) or 0):
            tags.append("action_sync_degraded")
            break
    if any((r.get("decision_ms") or 0) > C.FRAME_BUDGET_MS for r in window):
        tags.append("decision_over_frame_budget")
    elif any((r.get("decision_ms") or 0) > C.POLICY_BUDGET_MS for r in window):
        tags.append("decision_over_policy_budget")
    if any(r.get("act_mode") == "conservative" for r in window):
        tags.append("conservative_mode")
    tail = window[-30:]
    holds = [r.get("hold_applied") for r in tail if r.get("hold_applied") is not None]
    if holds and all((h & C.HOLD_DIRECTIONS) == 0 for h in holds):
        tags.append("no_movement_input")
    x, y = last.get("x"), last.get("y")
    if x is not None and y is not None and (
            x < C.EDGE_MARGIN or x > C.PLAYFIELD_W - C.EDGE_MARGIN or y < C.EDGE_MARGIN or y > C.PLAYFIELD_H - C.EDGE_MARGIN):
        tags.append("near_boundary")
    if not tags:
        tags.append("unclassified")
    return {
        "ref": record["ref"],
        "policy": record["policy"].get("name"),
        "event": {k: event[k] for k in event},
        "window": {"start_frame": first["frame"], "end_frame": last["frame"], "frames": len(window)},
        "actions": _rle(window),
        "position": {"start": [first.get("x"), first.get("y")], "end": [x, y]},
        "nearest_bullet": _nearest(window),
        "tags": tags,
        "evidence": {"trace": record["evidence"].get("trace"), "replay": record["evidence"].get("replay"),
                     "log": record["evidence"].get("log")},
    }


def collect(record, trace, window_frames=C.DEFAULT_PRE_HIT_WINDOW, max_per_episode=3):
    """평가 가능한 에피소드의 피격(hit) 이벤트마다 충돌 직전 구간 설명 하나. 사망은 피격 뒤에 오므로 따로 만들지 않는다."""
    if record["run"]["status"] != "completed" or not trace:
        return []
    out = []
    for e in record["events"]:
        if e["type"] == "hit" and len(out) < max_per_episode:
            ex = explain(record, trace, e, window_frames)
            if ex:
                out.append(ex)
    return out
