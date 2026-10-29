# evaluation

AI 반복 평가 도구와 결과 스키마 (이슈 [#23](https://github.com/kthss01/mini-danmaku-ai-claude/issues/23)). 정의·판정 규칙·사용법은 [docs/ai/EVALUATION.md](../docs/ai/EVALUATION.md)를 본다.

| 경로 | 내용 |
| --- | --- |
| `evaluate.py` | 명령줄 진입점 (`evaluate`·`compare`·`plan`·`validate`) |
| `taisei_eval/` | 도구 본체 (표준 라이브러리만). `judge.py` 판정, `summarize.py` 그룹 요약, `compare.py` 기준선 비교, `failure.py` 충돌 직전 구간 |
| `schemas/` | JSON Schema: run·episode·trace(입력), evaluation·comparison(출력) |
| `configs/eval-set-v0.json` | 초기 한 패턴용 고정 평가 세트 제안 |

검증은 `tests/ai-evaluation/`의 합성 fixture로 한다. fixture 결과는 실제 게임 결과가 아니다.
