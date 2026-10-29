# tests/ai-evaluation

평가 도구(`evaluation/`)의 fixture 기반 unittest. **합성 데이터**이며 실제 게임·브리지·실행기 결과가 아니다.

```bash
python -m unittest discover -s tests/ai-evaluation -v
```

- `fixture_builder.py`: 실행 계약 v1 미확정 상태에서 #20 v0.1과 브리지 계약 v1을 가정해 run 폴더를 만든다(결정적).
- `test_evaluation.py`: 스키마, 상태 판정, 분모, 지표, 시드 설계, 비교, CLI, 입력 불변.
