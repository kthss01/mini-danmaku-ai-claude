"""평가 도구 검증용 합성 run 폴더 생성기.

**이 데이터는 실제 게임 결과가 아니다.** 실행 계약 v1 미확정 상태에서 #20 v0.1과 브리지 계약 v1을 가정해
손으로 만든 fixture이며, 정책 성능이나 게임 동작에 대해 아무것도 증명하지 않는다.
결정적이다(같은 입력이면 같은 파일). 사용:

    python tests/ai-evaluation/fixture_builder.py --out <폴더>
"""
import argparse
import json
import os

BASE_MIN = 0  # 시작 시각 기준: 2026-10-29T00:00Z + 분


def iso(minute):
    return "2026-10-29T%02d:%02d:00Z" % (minute // 60, minute % 60)


def make_trace(n, *, hits=(), hit_outcome="death", bombs=(), end="none", overflow=(), cheat=None, cheat_events_at=None,
               pause_at=None, ms_per_frame=16.67, decision_ms=0.8, hold="idle", missing_from=None, mode_conservative=(),
               skip_decision=False, gap_at=None, mismatch=False, kind="spell", episode_id=1):
    """n프레임 trace를 만든다. hits는 피격 시작 프레임, hit_outcome은 death|deathbomb."""
    DB = 8
    phase = [0] * n
    ev = {"hit": [0] * n, "death": [0] * n, "bomb": [0] * n}
    for h in hits:
        if h + 1 >= n:
            continue
        for k in range(DB):
            if h + k < n:
                phase[h + k] = 1
        ev["hit"][h] += 1
        if hit_outcome == "death":
            ev["death"][h + DB] += 1 if h + DB < n else 0
            for k in range(DB, DB + 60):
                if h + k < n:
                    phase[h + k] = 2
            for k in range(DB + 60, DB + 210):
                if h + k < n:
                    phase[h + k] = 3
        else:
            ev["bomb"][h + 4] += 1 if h + 4 < n else 0
            for k in range(4, 44):
                if h + k < n:
                    phase[h + k] = 4
            for k in range(44, 120):
                if h + k < n:
                    phase[h + k] = 3
    for b in bombs:
        ev["bomb"][b] += 1
        for k in range(40):
            if b + k < n:
                phase[b + k] = 4
    cum = {"hit": 0, "death": 0, "bomb": 0}
    lives = 3
    out = []
    wall = 0.0
    for f in range(n):
        for key in cum:
            cum[key] += ev[key][f]
        lives = 3 - cum["death"]
        if hold == "idle":
            h = 32
        elif hold == "move":
            h = 32 | (4 if (f // 30) % 2 == 0 else 8)
        else:
            h = 32 | (4 if (f // 20) % 2 == 0 else 8)
        x = 240.0 + (20 if (f // 30) % 2 else -20) if hold != "idle" else 240.0
        near = None
        for hf in hits:
            if hf - 30 <= f <= hf:
                d = (hf - f)
                near = [[7, x + d + 2, 500.0, 4.0], [8, x - 40, 480.0, 3.0]]
        pause_here = pause_at is not None and f == pause_at
        wall += ms_per_frame + (3000 if pause_here else 0)
        rec = {
            "frame": f, "episode_id": episode_id, "wall_ms": round(wall, 3), "phase": phase[f], "vulnerable": 1 if phase[f] in (0, 1) else 0,
            "owner_state": 2 if pause_here else 1, "owner_reason": "pause" if pause_here else "none",
            "lives": lives, "bombs": 3 - cum["bomb"], "x": x, "y": 500.0,
            "ev_hit": cum["hit"], "ev_death": cum["death"] + (1 if mismatch and f == n - 1 else 0), "ev_death_uncounted": 0,
            "ev_bomb": cum["bomb"], "continues": 0,
            "cheat_flags": (cheat or 0), "cheat_events": (1 if cheat_events_at is not None and f >= cheat_events_at else 0),
            "overflow": 1 if f in overflow else 0, "gameover": "NONE", "dialog_active": 0,
            "hold_applied": 0 if f == 0 else h, "act_hold": h, "act_edges": 0,
            "act_mode": "conservative" if f in mode_conservative else "normal",
            "decision_ms": None if skip_decision else decision_ms + (0.01 * (f % 7)),
            "act_applied": f, "act_stale": 0, "act_dup": 0,
            "act_missing": (f - missing_from + 1) if (missing_from is not None and f >= missing_from) else 0,
            "act_rejected": 0, "act_last_obs_frame": f - 1, "near": near,
        }
        out.append(rec)
    if end == "win":
        out[-1]["gameover"] = "WIN" if kind == "stage" else "SCORESCREEN"
    elif end == "defeat":
        out[-1]["gameover"] = "DEFEAT"
    if gap_at is not None:
        out = [r for r in out if r["frame"] != gap_at]
    return out


def write_episode(run_dir, run_id, idx, *, policy, kind="spell", flavor="release", seed=None, seed_required=False, limits=None,
                  runner_status="completed", runner_reason="spell_end", trace=None, transitions=None, started_min=0,
                  shot_inverted=1, scenario_id="s1-spell1", final_go=None, raw_bytes=None, error_message=None):
    ep_dir = os.path.join(run_dir, "episodes")
    os.makedirs(ep_dir, exist_ok=True)
    path = os.path.join(ep_dir, f"{idx:04d}.json")
    if raw_bytes is not None:
        with open(path, "wb") as f:
            f.write(raw_bytes)
        return
    control = "set" if seed is not None else "random"
    ep = {
        "schema": "taisei-ai-episode/1", "run_id": run_id, "experiment_id": "fixture-" + policy[0], "episode_index": idx, "episode_id": 1,
        "started_at": iso(started_min), "ended_at": iso(started_min + 1),
        "code": {"main_commit": "9a81036", "taisei_commit": "1d4b468d", "dirty": False, "build_flavor": flavor,
                 "rules_preserved": "original" if flavor == "release" else "unverified", "build_info_sha256": "0" * 64, "wasm_sha256": "1" * 64},
        "config": {
            "scenario": {"kind": kind, "id": scenario_id, "difficulty": "Easy", "character": "marisa", "shot": "marisaA"},
            "policy": {"name": policy[0], "version": policy[1], "params_sha256": None},
            "seed": {"control": control, "required": seed_required, "requested": seed,
                     "actual": ("0x%016x" % seed) if seed is not None else "0x00000000deadbeef",
                     "source": "set" if seed is not None else "random"},
            "limits": limits or {"max_frames": 600, "wall_timeout_s": 60},
            "shot_inverted": shot_inverted, "shot_inverted_source": "web_default", "pre_hit_window_frames": 60,
            "observation": "taisei.ai.obs/1",
        },
        "run": {"status": runner_status, "reason": runner_reason, "exit_code": None, "elapsed_s": 10.0, "error_message": error_message},
        "owner_transitions": transitions or [],
        "final": {"gameover": final_go or "NONE", "last_frame": trace[-1]["frame"] if trace else None},
        "evidence": {"trace": f"episodes/{idx:04d}.trace.jsonl" if trace is not None else None, "replay": None, "log": "logs/runner.log"},
    }
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ep, f, ensure_ascii=False, indent=1)
    if trace is not None:
        with open(os.path.join(ep_dir, f"{idx:04d}.trace.jsonl"), "w", encoding="utf-8", newline="\n") as f:
            for r in trace:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")


def write_run_json(run_dir, run_id, policy, requested, *, kind="spell", flavor="release", limits=None, exit_code=0, shot_inverted=1, seed_required=False):
    os.makedirs(run_dir, exist_ok=True)
    rj = {
        "schema": "taisei-ai-run/1", "run_id": run_id, "experiment_id": "fixture-" + policy[0], "started_at": iso(0), "ended_at": iso(59),
        "exit_code": exit_code, "requested_episodes": requested, "command": ["python", "scripts/ai/run.py", "--policy", policy[0]],
        "code": {"main_commit": "9a81036", "taisei_commit": "1d4b468d", "dirty": False, "build_flavor": flavor,
                 "rules_preserved": "original" if flavor == "release" else "unverified"},
        "config": {
            "scenario": {"kind": kind, "id": "s1-spell1", "difficulty": "Easy", "character": "marisa", "shot": "marisaA"},
            "policy": {"name": policy[0], "version": policy[1]},
            "seed": {"control": "random", "required": seed_required},
            "limits": limits or {"max_frames": 600, "wall_timeout_s": 60},
            "shot_inverted": shot_inverted,
        },
    }
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rj, f, ensure_ascii=False, indent=1)


def build_policy_run(out_root, run_id, policy, plan, *, slot=0, nslots=1, **kw):
    """plan: 에피소드 spec 목록. spec은 dict(kind=..., 나머지는 make_trace 인자)."""
    run_dir = os.path.join(out_root, run_id)
    write_run_json(run_dir, run_id, policy, len(plan), **{k: v for k, v in kw.items() if k in ("flavor", "limits", "kind", "shot_inverted")})
    for i, spec in enumerate(plan, 1):
        spec = dict(spec)
        t = spec.pop("t", "survive")
        start = (i - 1) * nslots + slot
        base = dict(policy=policy, started_min=start, **{k: v for k, v in kw.items() if k in ("flavor", "limits", "kind", "shot_inverted")})
        hold = spec.pop("hold", {"idle": "idle", "simple-move": "move"}.get(policy[0], "avoid"))
        seed = spec.pop("seed", None)
        if t == "missing":
            continue
        if t == "unreadable":
            write_episode(run_dir, run_id, i, raw_bytes=b"{ not json", **base)
            continue
        n = spec.pop("n", 300)
        kind = kw.get("kind", "spell")
        if t == "survive":
            tr = make_trace(n, hold=hold, end=spec.pop("end", "win"), kind=kind, **spec)
            go = tr[-1]["gameover"]
            write_episode(run_dir, run_id, i, seed=seed, trace=tr, runner_reason="spell_end", final_go=go, **base)
        elif t == "limit":
            n = (kw.get("limits") or {"max_frames": 600})["max_frames"]
            tr = make_trace(n, hold=hold, kind=kind, **spec)
            write_episode(run_dir, run_id, i, seed=seed, trace=tr, runner_reason="frame_limit", **base)
        elif t == "defeat":
            tr = make_trace(n, hold=hold, end="defeat", kind=kind, **spec)
            write_episode(run_dir, run_id, i, seed=seed, trace=tr, runner_reason="game_over", final_go="DEFEAT", **base)
        elif t == "timeout":
            tr = make_trace(120, hold=hold, kind=kind)
            write_episode(run_dir, run_id, i, seed=seed, trace=tr, runner_status="timeout", runner_reason="wall_timeout", **base)
        elif t == "error":
            write_episode(run_dir, run_id, i, seed=seed, trace=None, runner_status="error", runner_reason="runner_error",
                          error_message="browser crashed", **base)
        elif t == "aborted":
            tr = make_trace(80, hold=hold, kind=kind)
            write_episode(run_dir, run_id, i, seed=seed, trace=tr, runner_status="aborted", runner_reason="user_abort", **base)
        elif t == "trace_missing":
            write_episode(run_dir, run_id, i, seed=seed, trace=None, runner_reason="spell_end", **base)
        elif t == "seed_unsupported":
            tr = make_trace(n, hold=hold, end="win", kind=kind)
            write_episode(run_dir, run_id, i, seed=None, seed_required=True, trace=tr, runner_reason="spell_end", **base)
        elif t == "transition":
            tr = make_trace(n, hold=hold, end=spec.pop("end", "none"), kind=kind)
            trans = spec.pop("transitions")
            write_episode(run_dir, run_id, i, seed=seed, trace=tr, transitions=trans, runner_reason="frame_limit", **base)
        else:
            raise ValueError(t)
    return run_dir


# ---- 표준 샘플: 한 패턴, 정책 3종, 같은 조건, 시드 미통제(탐색 비교), 시작 시각을 번갈아 배치
def sample_plans():
    idle = [
        {"t": "defeat", "hits": [60, 330], "n": 450, "hit_outcome": "death"},
        {"t": "defeat", "hits": [90], "n": 200},
        {"t": "survive", "hits": [100], "hit_outcome": "deathbomb", "n": 300},
        {"t": "defeat", "hits": [40], "n": 160},
        {"t": "timeout"},
        {"t": "defeat", "hits": [70], "n": 180},
    ]
    simple = [
        {"t": "survive", "n": 300},
        {"t": "defeat", "hits": [150], "n": 240},
        {"t": "survive", "hits": [120], "hit_outcome": "deathbomb", "n": 300},
        {"t": "defeat", "hits": [80], "n": 200},
        {"t": "error"},
        {"t": "survive", "n": 300, "overflow": range(100, 110)},
    ]
    avoid = [
        {"t": "survive", "n": 300},
        {"t": "survive", "n": 300},
        {"t": "survive", "n": 300, "bombs": [100]},
        {"t": "defeat", "hits": [220], "n": 300, "mode_conservative": range(180, 220)},
        {"t": "survive", "n": 300},
        {"t": "missing"},
    ]
    return idle, simple, avoid


def build_sample(out_root):
    idle, simple, avoid = sample_plans()
    runs = {}
    for slot, (pol, plan) in enumerate((("idle", idle), ("simple-move", simple), ("avoid-v1", avoid))):
        policy = (pol, "fixture-0")
        run_id = "20261029T0%d0000Z-%06x" % (slot, 0xabc000 + slot)
        runs[pol] = build_policy_run(out_root, run_id, policy, plan, slot=slot, nslots=3)
    return runs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    for k, v in build_sample(a.out).items():
        print(k, v)
