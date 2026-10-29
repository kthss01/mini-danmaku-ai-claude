# AI 실험 설정

`scripts/ai/run.py --config <파일>`이 읽는 JSON 설정 예시입니다. 키는 실행 인자 이름(`_` 표기)과 같고, 명령줄 인자가 설정 파일보다 우선합니다. 알 수 없는 키는 오류(종료 코드 2)입니다. 인자 목록과 계약은 [docs/ai/RUNNER.md](../../docs/ai/RUNNER.md)를 봅니다.

| 파일 | 용도 |
| --- | --- |
| `smoke.json` | 브리지 없이 릴리스 빌드의 셸이 `playing`에 이르는지만 확인 |
| `spell-baseline.example.json` | 개발자 빌드에서 스펠 하나를 반복하는 예시. 스펠 ID는 실제 값으로 바꿔야 하고, 브리지(#21)가 있는 빌드에서만 동작 |
