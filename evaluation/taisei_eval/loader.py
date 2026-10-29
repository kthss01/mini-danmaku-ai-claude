"""run 폴더 읽기: run.json, episodes/NNNN.json, trace(jsonl).

읽기 실패를 예외로 끝내지 않고 항목마다 오류를 달아 돌려준다. 누락·손상은 평가에서 `missing` 상태로 남는다.
"""
import json
import os
import re

from . import schema_lite

EP_RE = re.compile(r"^(\d{4})\.json$")


class LoadedEpisode:
    def __init__(self, index):
        self.index = index
        self.file = None         # run 폴더 기준 상대 경로
        self.episode = None      # dict 또는 None
        self.trace = None        # 레코드 목록 또는 None
        self.trace_path = None
        self.errors = []         # 읽기 단계 오류
        self.schema_errors = []  # 에피소드 파일 스키마 위반
        self.trace_errors = []   # trace 줄 스키마·JSON 위반
        self.missing = False     # 파일 자체가 없음
        self.unreadable = False  # 있으나 읽거나 해석하지 못함


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_run(run_dir):
    """(run_json 또는 None, run_json 오류 목록, {index: LoadedEpisode}, requested 또는 None)"""
    run_json, run_errors = None, []
    rp = os.path.join(run_dir, "run.json")
    if os.path.isfile(rp):
        try:
            run_json = _read_json(rp)
            if not isinstance(run_json, dict):
                run_errors.append("run.json이 객체가 아님")
                run_json = None
            else:
                run_errors += schema_lite.validate(run_json, "run.schema.json")
        except (OSError, ValueError) as e:
            run_errors.append(f"run.json 읽기 실패: {e}")
            run_json = None
    else:
        run_errors.append("run.json 없음")

    requested = None
    if isinstance(run_json, dict) and isinstance(run_json.get("requested_episodes"), int):
        requested = run_json["requested_episodes"]

    items = {}
    ep_dir = os.path.join(run_dir, "episodes")
    if os.path.isdir(ep_dir):
        for name in sorted(os.listdir(ep_dir)):
            m = EP_RE.match(name)
            if not m:
                continue
            idx = int(m.group(1))
            items[idx] = _load_episode(run_dir, idx, f"episodes/{name}")

    return run_json, run_errors, items, requested


def _load_episode(run_dir, idx, rel):
    le = LoadedEpisode(idx)
    le.file = rel
    path = os.path.join(run_dir, rel)
    try:
        data = _read_json(path)
    except (OSError, ValueError) as e:
        le.unreadable = True
        le.errors.append(f"에피소드 파일 읽기 실패: {e}")
        return le
    if not isinstance(data, dict):
        le.unreadable = True
        le.errors.append("에피소드 파일이 객체가 아님")
        return le
    le.episode = data
    le.schema_errors = schema_lite.validate(data, "episode.schema.json")

    ev = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
    trace_rel = ev.get("trace") or f"episodes/{idx:04d}.trace.jsonl"
    le.trace_path = trace_rel
    tp = os.path.join(run_dir, trace_rel)
    if os.path.isfile(tp):
        le.trace, le.trace_errors = read_trace(tp)
    return le


def read_trace(path, max_errors=5):
    """jsonl을 읽는다. 해석하지 못한 줄은 건너뛰고 오류에 남긴다(오류는 max_errors개까지만 기록, 개수는 항상 센다)."""
    recs, errors, bad = [], [], 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError as e:
                    bad += 1
                    if len(errors) < max_errors:
                        errors.append(f"{lineno}행: JSON 해석 실패 ({e})")
                    continue
                errs = schema_lite.validate(rec, "trace.schema.json", max_errors=3) if isinstance(rec, dict) else ["객체가 아님"]
                if errs:
                    bad += 1
                    if len(errors) < max_errors:
                        errors.append(f"{lineno}행: {errs[0]}")
                    continue
                recs.append(rec)
    except OSError as e:
        return None, [f"trace 읽기 실패: {e}"]
    if bad > len(errors):
        errors.append(f"(그 밖에 {bad - len(errors)}개 줄 오류 생략)")
    return recs, errors
