"""명령줄: evaluate / compare / plan / validate.

종료 코드: 0 정상, 2 인자·입력 오류, 3 출력이 스키마를 만족하지 않음(도구 오류).
평가 대상 에피소드의 실패·누락은 종료 코드에 영향을 주지 않는다(리포트에 남는다).
"""
import argparse
import json
import os
import sys

from . import compare as cmpmod
from . import pipeline, plan, schema_lite

SCHEMAS = {"run": "run.schema.json", "episode": "episode.schema.json", "trace": "trace.schema.json",
           "evaluation": "evaluation.schema.json", "comparison": "comparison.schema.json"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="evaluate.py", description="Taisei AI 평가 도구 (#23)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("evaluate", help="run 폴더 하나를 평가한다")
    e.add_argument("run_dir")
    e.add_argument("--out", help="출력 폴더(기본 <run_dir>/evaluation)")
    e.add_argument("--window", type=int, help="충돌 직전 구간 프레임 수(기본: 에피소드 설정, 없으면 120)")

    c = sub.add_parser("compare", help="평가 결과 여러 개를 기준선과 비교한다")
    c.add_argument("inputs", nargs="+", help="evaluation.json, 평가된 run 폴더, 또는 평가 전 run 폴더")
    c.add_argument("--out", required=True)
    c.add_argument("--baselines", default="idle,simple-move")

    p = sub.add_parser("plan", help="고정 평가 세트를 실행 순서 목록으로 펼친다")
    p.add_argument("--set", dest="evalset", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs", "eval-set-v0.json"))
    p.add_argument("--mode", choices=["seeded", "uncontrolled"], default="seeded")
    p.add_argument("--holdout", action="store_true")
    p.add_argument("--out")

    v = sub.add_parser("validate", help="JSON 파일을 스키마로 검증한다")
    v.add_argument("kind", choices=sorted(SCHEMAS) + ["trace-file"])
    v.add_argument("file")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "evaluate":
            if not os.path.isdir(a.run_dir):
                print(f"run 폴더가 없다: {a.run_dir}", file=sys.stderr)
                return 2
            res = pipeline.evaluate_run(a.run_dir, a.window)
            out = a.out or os.path.join(a.run_dir, "evaluation")
            paths, errs = pipeline.write_outputs(res, out)
            for g in res["groups"]:
                c_ = g["counts"]
                print(f"[{g['policy'].get('name')}] 시작 {c_['started']} / 평가 가능 {c_['evaluable']} / 상태 {c_['by_status']} / 설계 {g['seed_design']}")
            print("출력:", ", ".join(paths.values()))
            if errs:
                print("출력이 스키마를 만족하지 않음:", *errs, sep="\n  ", file=sys.stderr)
                return 3
            return 0
        if a.cmd == "compare":
            res = cmpmod.compare(a.inputs, tuple(x for x in a.baselines.split(",") if x))
            paths, errs = cmpmod.write_outputs(res, a.out)
            print("출력:", ", ".join(paths))
            if errs:
                print("출력이 스키마를 만족하지 않음:", *errs, sep="\n  ", file=sys.stderr)
                return 3
            return 0
        if a.cmd == "plan":
            with open(a.evalset, "r", encoding="utf-8") as f:
                es = json.load(f)
            rows = plan.expand(es, a.mode, a.holdout)
            text = json.dumps({"schema": "taisei-ai-plan/1", "evalset": es["id"], "mode": a.mode, "episodes": rows}, ensure_ascii=False, indent=2)
            if a.out:
                with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text + "\n")
                print(f"{len(rows)}개 에피소드 → {a.out}")
            else:
                print(text)
            return 0
        if a.cmd == "validate":
            if a.kind == "trace-file":
                from . import loader
                recs, errs = loader.read_trace(a.file)
                print(f"유효한 줄 {len(recs or [])}개")
            else:
                with open(a.file, "r", encoding="utf-8") as f:
                    errs = schema_lite.validate(json.load(f), SCHEMAS[a.kind])
            if errs:
                print(*errs, sep="\n")
                return 3
            print("통과")
            return 0
    except (OSError, ValueError) as ex:
        print(f"입력 오류: {ex}", file=sys.stderr)
        return 2
    return 0
