"""에피소드 판정: trace → 이벤트·지표·품질 → run.status/result.

판정 주체 분담(#23 v0.2): 실행기는 completed/timeout/aborted/error와 원시 사실을 쓰고, 평가 도구가
invalid/unsupported/missing과 result·events·metrics·quality를 판정한다. 실행기 판정을 바꿀 때는
`run.status_by_runner`에 원래 값을 남긴다. 입력 파일은 고치지 않는다.
"""
from . import constants as C
from . import stats

SUCCESS_REASONS = ("frame_limit", "spell_end", "stage_end", "game_over")


# ---------------------------------------------------------------- 이벤트

def derive_events(trace):
    """phase 전이로 hit/death/deathbomb/bomb 이벤트를 만든다(CONTRACT.md 2.3). 카운터로 추정하지 않는다."""
    events = []
    prev = None
    for rec in trace:
        if prev is not None and rec["phase"] != prev["phase"]:
            a, b, f = prev["phase"], rec["phase"], rec["frame"]
            if a == C.PHASE_NORMAL and b == C.PHASE_HIT_PENDING:
                events.append({"frame": f, "type": "hit"})
            elif a == C.PHASE_HIT_PENDING and b == C.PHASE_DEAD:
                counted = rec["ev_death_uncounted"] == prev["ev_death_uncounted"]
                events.append({"frame": f, "type": "death", "counted": counted})
            elif a == C.PHASE_HIT_PENDING and b == C.PHASE_BOMBING:
                events.append({"frame": f, "type": "deathbomb", "source": "deathbomb"})
            elif a in (C.PHASE_NORMAL, C.PHASE_RECOVERING) and b == C.PHASE_BOMBING:
                events.append({"frame": f, "type": "bomb", "source": "policy"})
            elif a == C.PHASE_NORMAL and b == C.PHASE_DEAD:
                # 관측 사이에서 hit_pending을 건너뛴 경우. 이벤트는 만들되 추정 표시를 단다.
                events.append({"frame": f, "type": "hit", "inferred": True})
                counted = rec["ev_death_uncounted"] == prev["ev_death_uncounted"]
                events.append({"frame": f, "type": "death", "counted": counted, "inferred": True})
        prev = rec
    return events


def _transitions(ep, trace):
    tr = ep.get("owner_transitions")
    if isinstance(tr, list) and tr:
        return [t for t in tr if isinstance(t, dict)]
    out, prev = [], None
    for rec in trace or []:
        if prev is not None and rec["owner_state"] != prev["owner_state"]:
            out.append({"frame": rec["frame"], "state": C.OWNER_NAMES.get(rec["owner_state"], "manual"),
                        "reason": rec["owner_reason"]})
        prev = rec
    return out


def _owner_events(transitions):
    ev = []
    for t in transitions:
        if t.get("state") == "ai_suspended":
            ev.append({"frame": t.get("frame"), "type": "suspend", "reason": t.get("reason", "none")})
        elif t.get("state") == "ai_active" and ev and ev[-1]["type"] == "suspend":
            ev.append({"frame": t.get("frame"), "type": "resume", "reason": t.get("reason", "none")})
    return ev


# ---------------------------------------------------------------- 지표

def _decision_stats(trace):
    vals = [r["decision_ms"] for r in trace if r.get("decision_ms") is not None]
    if not vals:
        return None, []
    return ({"n": len(vals), "p50": round(stats.percentile(vals, 50), 3), "p95": round(stats.percentile(vals, 95), 3),
             "max": round(max(vals), 3),
             "over_policy_budget": sum(1 for v in vals if v > C.POLICY_BUDGET_MS),
             "over_frame_budget": sum(1 for v in vals if v > C.FRAME_BUDGET_MS)}, vals)


def _input_lag(trace):
    lags, prev_applied = [], 0
    for r in trace:
        a = r.get("act_applied")
        if a is None or r.get("act_last_obs_frame") is None:
            continue
        if a > prev_applied:
            lags.append(r["frame"] - r["act_last_obs_frame"])
        prev_applied = a
    if not lags:
        return None
    return {"n": len(lags), "p50": stats.percentile(lags, 50), "max": max(lags)}


def _sim_fps(trace):
    """일시정지·AI 정지 구간(owner_state != 1)과 프레임이 이어지지 않는 구간을 뺀 실행 속도."""
    dts = []
    for a, b in zip(trace, trace[1:]):
        if a.get("wall_ms") is None or b.get("wall_ms") is None:
            continue
        if b["frame"] - a["frame"] != 1 or a["owner_state"] != 1 or b["owner_state"] != 1:
            continue
        dt = b["wall_ms"] - a["wall_ms"]
        if dt < 0:
            continue
        dts.append(dt)
    if not dts or sum(dts) <= 0:
        return None
    total_s = sum(dts) / 1000.0
    out = {"frames": len(dts), "mean": round(len(dts) / total_s, 2), "windows": 0, "below_60_ratio": None,
           "slow_threshold": C.SIM_FPS_SLOW_THRESHOLD}
    w = C.SIM_FPS_WINDOW
    wins = [sum(dts[i:i + w]) for i in range(0, len(dts) - w + 1, w)]
    if wins:
        slow = sum(1 for s in wins if s > 0 and (w / (s / 1000.0)) < C.SIM_FPS_SLOW_THRESHOLD)
        out["windows"] = len(wins)
        out["below_60_ratio"] = round(slow / len(wins), 4)
    return out


# ---------------------------------------------------------------- 품질·규칙

def _quality(trace, transitions):
    kinds, ovf_frames, cons, dlg = set(), 0, 0, 0
    for r in trace:
        if r["overflow"]:
            ovf_frames += 1
            for bit, name in C.OVERFLOW_KINDS:
                if r["overflow"] & bit:
                    kinds.add(name)
        if r.get("act_mode") == "conservative":
            cons += 1
        if r.get("dialog_active"):
            dlg += 1
    gaps = 0
    for a, b in zip(trace, trace[1:]):
        if b["frame"] - a["frame"] != 1:
            gaps += abs(b["frame"] - a["frame"] - 1) if b["frame"] > a["frame"] else 1
    last = trace[-1] if trace else {}
    sync = {k: last.get("act_" + k) for k in ("stale", "dup", "missing", "rejected", "applied")}
    return {
        "overflow_frames": ovf_frames,
        "overflow_kinds": [n for _, n in C.OVERFLOW_KINDS if n in kinds],
        "observation_complete": ovf_frames == 0 and gaps == 0,
        "frame_gaps": gaps,
        "conservative_frames": cons,
        "dialog_frames": dlg,
        "action_sync": sync,
    }


def _rule_flags(trace):
    flags = set()
    for r in trace:
        cf = r["cheat_flags"]
        if cf & C.CHEAT_IDDQD:
            flags.add("iddqd")
        if cf & C.CHEAT_REPLAY_FLAG:
            flags.add("replay_cheat_flag")
        if cf & C.CHEAT_SKIP:
            flags.add("skip_mode")
        if r["cheat_events"] > 0:
            flags.add("cheat_events")
        if r["phase"] == C.PHASE_NORMAL and r.get("vulnerable") == 0:
            flags.add("invulnerable_in_normal_phase")
    return sorted(flags)


def _counters_check(trace, events):
    last = trace[-1]
    n = lambda t: sum(1 for e in events if e["type"] == t)  # noqa: E731
    deaths_all = [e for e in events if e["type"] == "death"]
    exp = {
        "hit": (n("hit"), last["ev_hit"]),
        "death": (len(deaths_all), last["ev_death"]),
        "death_uncounted": (sum(1 for e in deaths_all if not e.get("counted", True)), last["ev_death_uncounted"]),
        "bomb": (n("bomb") + n("deathbomb"), last["ev_bomb"]),
    }
    mism = [f"{k}: 이벤트 {a} != 카운터 {b}" for k, (a, b) in exp.items() if a != b]
    return {"consistent": not mism, "mismatches": mism}


# ---------------------------------------------------------------- 상태 판정

def _end_condition(ep, trace, kind, max_frames):
    """(reason 또는 None, gameover 이름). 정상 종료 사유를 찾지 못하면 reason=None."""
    go = "NONE"
    for r in trace:
        if r["gameover"] != "NONE":
            go = r["gameover"]
    fin = ep.get("final")
    if isinstance(fin, dict) and fin.get("gameover") and fin["gameover"] != "NONE":
        go = fin["gameover"]
    frames_total = trace[-1]["frame"] - trace[0]["frame"] + 1
    if go in ("WIN", "SCORESCREEN"):
        return ("spell_end" if kind == "spell" else "stage_end"), go
    if max_frames and frames_total >= max_frames:
        return "frame_limit", go
    if go == "DEFEAT":
        return "game_over", go
    if go in ("ABORT", "RESTART"):
        return "user_abort", go
    return None, go


def _status_candidates(ep, cfg, trace, transitions, flags, counters, quality, le_errors):
    """completed로 기록된 에피소드를 바꿀 사유를 우선순위 순으로 모은다."""
    cands = []  # (우선순위, status, reason, reason_code, note)
    if flags:
        cands.append((1, "invalid", "rule_violation", None, "규칙 위반 표시: " + ", ".join(flags)))
    obs_notes = list(le_errors)
    if counters and not counters["consistent"]:
        obs_notes += ["카운터 불일치: " + "; ".join(counters["mismatches"])]
    if quality["frame_gaps"]:
        obs_notes.append(f"trace 프레임 누락·중복 {quality['frame_gaps']}개")
    ids = {r["episode_id"] for r in trace}
    if len(ids) > 1:
        obs_notes.append(f"trace에 episode_id가 여러 개: {sorted(ids)}")
    for t in transitions:
        if t.get("reason") == "observation_invalid":
            obs_notes.append("브리지가 observation_invalid 전환을 기록함")
    if obs_notes:
        cands.append((2, "invalid", "observation_invalid", "observation_invalid" if any("브리지" in n for n in obs_notes) else None,
                      "; ".join(obs_notes)))
    for t in transitions:
        if t.get("state") == "ai_suspended" and t.get("reason") in ("pause", "focus_lost"):
            cands.append((3, "invalid", "unexpected_pause", t["reason"], f"계획 외 정지 {t['reason']} (프레임 {t.get('frame')})"))
            break
    seed = cfg.get("seed") or {}
    if seed.get("required") and not (seed.get("source") == "set" or
                                     (seed.get("control") == "replay" and seed.get("source") == "replay")):
        cands.append((4, "unsupported", "seed_unsupported", None,
                      f"시드 지정을 요구했으나 출처가 {seed.get('source')!r} (control={seed.get('control')!r})"))
    for t in transitions:
        r = t.get("reason")
        if r == "policy_error" or (r == "policy_deadline" and t.get("state") == "ai_suspended"):
            cands.append((5, "error", "policy_error", r, f"정책 오류 전환 {r}"))
            break
    for t in transitions:
        if t.get("reason") == "bridge_error":
            cands.append((5, "error", "runner_error", "bridge_error", "브리지 내부 오류 전환"))
            break
    for t in transitions:
        if t.get("reason") == "user_input":
            cands.append((6, "aborted", "user_abort", "user_input", "AI 실행 중 사용자 키 입력"))
            break
    return cands


def _empty_quality():
    return {"overflow_frames": 0, "overflow_kinds": [], "observation_complete": False, "frame_gaps": 0,
            "conservative_frames": 0, "dialog_frames": 0,
            "action_sync": {"stale": None, "dup": None, "missing": None, "rejected": None, "applied": None},
            "counters_check": {"consistent": None, "mismatches": []}, "rule_flags": []}


def _identity(ep, run_json):
    """에피소드 파일이 모자라도 run.json의 공통 설정으로 그룹을 채운다."""
    src = ep if isinstance(ep, dict) else {}
    rj = run_json if isinstance(run_json, dict) else {}
    cfg = src.get("config") if isinstance(src.get("config"), dict) else (rj.get("config") if isinstance(rj.get("config"), dict) else {})
    code = src.get("code") if isinstance(src.get("code"), dict) else (rj.get("code") if isinstance(rj.get("code"), dict) else {})
    return cfg, code


def missing_record(idx, run_json, reason, file, notes):
    cfg, code = _identity(None, run_json)
    rj = run_json if isinstance(run_json, dict) else {}
    return _assemble(
        ref={"run_id": rj.get("run_id"), "episode_index": idx, "file": file},
        ep=None, cfg=cfg, code=code, experiment_id=rj.get("experiment_id"),
        run={"status": "missing", "reason": reason, "reason_code": None, "evaluable": False,
             "status_by_runner": {"status": None, "reason": None, "overridden": False}, "notes": notes},
        result=None, events=[], metrics=None, quality=_empty_quality(), evidence={"trace": None, "replay": None, "log": None}), {}


def _assemble(ref, ep, cfg, code, experiment_id, run, result, events, metrics, quality, evidence):
    scenario = cfg.get("scenario") or {}
    policy = cfg.get("policy") or {}
    seed = cfg.get("seed") or {}
    return {
        "ref": ref,
        "experiment_id": experiment_id,
        "policy": {"name": policy.get("name"), "version": policy.get("version"), "params_sha256": policy.get("params_sha256")},
        "scenario": {k: scenario.get(k) for k in ("kind", "id", "difficulty", "character", "shot")},
        "seed": {"control": seed.get("control"), "required": bool(seed.get("required")), "requested": seed.get("requested"),
                 "actual": seed.get("actual"), "source": seed.get("source")},
        "build_flavor": code.get("build_flavor"),
        "rules_preserved": code.get("rules_preserved"),
        "shot_inverted": cfg.get("shot_inverted"),
        "limits": cfg.get("limits"),
        "started_at": (ep or {}).get("started_at") if isinstance(ep, dict) else None,
        "run": run, "result": result, "events": events, "metrics": metrics, "quality": quality, "evidence": evidence,
    }


def evaluate_loaded(le, run_json):
    """LoadedEpisode 하나를 판정한다. (평가 레코드, 내부 데이터{trace, decision_samples}) 반환."""
    if le.missing:
        return missing_record(le.index, run_json, "episode_file_missing", None, ["episodes/ 에 파일이 없음"])
    if le.unreadable:
        return missing_record(le.index, run_json, "episode_file_unreadable", le.file, le.errors)

    ep = le.episode
    cfg, code = _identity(ep, run_json)
    limits = cfg.get("limits") or {}
    max_frames = limits.get("max_frames")
    kind = (cfg.get("scenario") or {}).get("kind")
    runner = ep.get("run") if isinstance(ep.get("run"), dict) else {}
    r_status, r_reason = runner.get("status"), runner.get("reason")
    notes = []

    trace = le.trace or []
    transitions = _transitions(ep, trace)
    evidence = dict(ep.get("evidence") or {})
    evidence.setdefault("trace", le.trace_path if le.trace is not None else None)

    events = derive_events(trace) if trace else []
    events += _owner_events(transitions)
    quality = _quality(trace, transitions) if trace else _empty_quality()
    flags = _rule_flags(trace) if trace else []
    counters = _counters_check(trace, events) if trace else {"consistent": None, "mismatches": []}
    quality["counters_check"] = counters
    quality["rule_flags"] = flags

    le_errors = []
    if le.schema_errors:
        le_errors.append("에피소드 스키마 위반: " + "; ".join(le.schema_errors[:3]))
    if le.trace_errors:
        le_errors.append("trace 오류: " + "; ".join(le.trace_errors[:3]))
    if ep.get("episode_index") not in (None, le.index):
        le_errors.append(f"파일 번호 {le.index}와 episode_index {ep.get('episode_index')} 불일치")

    metrics = _metrics(trace, events, flags) if trace else None
    internals = {"trace": trace, "decision_samples": (metrics or {}).pop("_decision_samples", []) if metrics else []}

    # ---- 상태
    status, reason, code_str = r_status, r_reason, None
    if r_status == "completed":
        if not trace:
            cands = [(2, "invalid", "observation_invalid", None, "completed인데 trace가 없거나 비어 있음" + ("; " + "; ".join(le_errors) if le_errors else ""))]
        else:
            cands = _status_candidates(ep, cfg, trace, transitions, flags, counters, quality, le_errors)
        # 정상 종료 조건
        end_reason, go = (None, "NONE")
        if trace:
            end_reason, go = _end_condition(ep, trace, kind, max_frames)
        if cands:
            cands.sort(key=lambda c: c[0])
            _, status, reason, code_str, note = cands[0]
            notes.append(note)
            for c in cands[1:]:
                notes.append(f"(추가 사유: {c[2]}) {c[4]}")
        elif end_reason in SUCCESS_REASONS:
            status, reason = "completed", end_reason
        elif end_reason == "user_abort":
            status, reason, code_str = "aborted", "user_abort", None
            notes.append(f"종료 유형 {go}: 정상 종료 조건이 아님")
        else:
            status, reason = "invalid", "observation_invalid"
            notes.append("정상 종료 조건을 trace에서 찾지 못함(스펠·스테이지 종료, 한도, 게임오버 모두 아님)")
        # 재시작 전환은 정상 종료 뒤가 아니면 중단
        if status == "completed":
            for t in transitions:
                if t.get("reason") == "restart" and end_reason not in ("spell_end", "stage_end", "frame_limit", "game_over"):
                    status, reason, code_str = "aborted", "user_abort", "restart"
                    notes.append("정상 종료 없이 재시작 전환")
                    break
    else:
        if status not in ("timeout", "aborted", "error"):
            status, reason = "invalid", "observation_invalid"
            notes.append(f"실행기 상태 {r_status!r}를 알 수 없음")
        else:
            reason = {"timeout": "wall_timeout", "aborted": "user_abort", "error": "runner_error"}.get(status) if r_reason not in _KNOWN_REASONS else r_reason
        if flags:
            notes.append("참고 규칙 위반 표시: " + ", ".join(flags))
    if reason not in _KNOWN_REASONS:
        notes.append(f"알 수 없는 사유 {reason!r} → unknown")
        reason = "unknown"

    overridden = (r_status != status)
    run = {"status": status, "reason": reason, "reason_code": code_str,
           "evaluable": status == "completed",
           "status_by_runner": {"status": r_status, "reason": r_reason, "overridden": overridden},
           "notes": notes}
    if runner.get("error_message"):
        run["notes"].append("실행기 오류: " + str(runner["error_message"])[:200])

    result = _result(trace, events, reason, kind, quality, metrics) if status == "completed" else None
    return _assemble(
        ref={"run_id": ep.get("run_id"), "episode_index": le.index, "file": le.file},
        ep=ep, cfg=cfg, code=code, experiment_id=ep.get("experiment_id"),
        run=run, result=result, events=events, metrics=metrics, quality=quality, evidence=evidence), internals


_KNOWN_REASONS = ("frame_limit", "spell_end", "stage_end", "game_over", "wall_timeout", "user_abort", "runner_error",
                  "policy_error", "observation_invalid", "rule_violation", "unexpected_pause", "seed_unsupported",
                  "episode_file_missing", "episode_file_unreadable", "unknown")


def _metrics(trace, events, flags):
    first, last = trace[0], trace[-1]
    n = lambda t: sum(1 for e in events if e["type"] == t)  # noqa: E731
    deaths = [e for e in events if e["type"] == "death" and e.get("counted", True)]
    frames_total = last["frame"] - first["frame"] + 1
    death_frame = deaths[0]["frame"] if deaths else None
    frames_survived = (death_frame - first["frame"]) if death_frame is not None else frames_total
    dec, samples = _decision_stats(trace)
    hold_vals = [r["hold_applied"] for r in trace if r.get("hold_applied") is not None]
    unavailable = []
    lag = _input_lag(trace)
    fps = _sim_fps(trace)
    for name, v in (("decision_ms", dec), ("input_lag_frames", lag), ("sim_fps", fps), ("shot_hold_ratio", hold_vals or None)):
        if not v:
            unavailable.append(name)
    return {
        "frames_survived": frames_survived,
        "seconds_survived": round(frames_survived / C.FPS, 3),
        "frames_total": frames_total,
        "hits": n("hit"),
        "deaths": len(deaths),
        "deathbombs": n("deathbomb"),
        "uncounted_deaths": sum(1 for e in events if e["type"] == "death" and not e.get("counted", True)),
        "bombs_policy": n("bomb"),
        "bombs_deathbomb": n("deathbomb"),
        "continues": last["continues"],
        "shot_hold_ratio": (round(sum(1 for h in hold_vals if h & C.HOLD_SHOT) / len(hold_vals), 4) if hold_vals else None),
        "decision_ms": dec,
        "input_lag_frames": lag,
        "sim_fps": fps,
        "unavailable": unavailable,
        "_decision_samples": samples,
    }


def _result(trace, events, reason, kind, quality, metrics):
    deaths = [e for e in events if e["type"] == "death" and e.get("counted", True)]
    last_go = "NONE"
    for r in trace:
        if r["gameover"] != "NONE":
            last_go = r["gameover"]
    survived = not deaths
    ended_cleanly = reason in ("spell_end", "stage_end")
    captured = None
    cleared = None
    if kind == "spell":
        captured = bool(ended_cleanly and metrics["hits"] == 0 and metrics["bombs_policy"] + metrics["bombs_deathbomb"] == 0 and survived)
    elif kind == "stage":
        cleared = bool(ended_cleanly and survived and metrics["continues"] == 0)
    return {"survived": survived, "first_death_frame": deaths[0]["frame"] if deaths else None,
            "pattern_captured": captured, "stage_cleared": cleared, "gameover_type": last_go}
