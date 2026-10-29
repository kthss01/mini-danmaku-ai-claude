# AI 실험 실행기 테스트

`scripts/ai/**`(이슈 #20)의 테스트입니다. **fixture 검증**이며 실제 게임과 브리지는 쓰지 않습니다.

- `fixture/game/index.html`: 웹 셸(`window.taiseiShell`)과 브리지 호스트 API(`window.taiseiAI`)를 흉내 내는 모의 페이지. `window.taiseiAIRun.policy.name`(`fixture-idle`·`fixture-hang`·`fixture-crash`·`fixture-leak`·`fixture-artifact`·`fixture-nobridge`·`fixture-stuck`·`fixture-stageend`·`fixture-framecap`·`fixture-userkey`·`fixture-notplaying`)으로 동작을 고릅니다.
- `_support.py`: fixture site 생성(`build-info.json` 포함), 실행기 호출, 임시 프로필·브라우저 프로세스 누수 확인.
- `test_runner.py`
  - 브라우저 없이: CDP WebSocket 프레임, 인자 검증과 종료 코드 2·3, 실패 기록(`run.json`)
  - 브라우저 필요(Chrome/Edge가 없으면 건너뜀): 정상 완료, 브리지 상태로 종료 파생(`episode_end` 없이 stage_end·frame_limit·user_input·not_playing), 시간 초과, 셸 오류, 입력 누수(종료 코드 6), 브리지 없음·시작 시간 초과(종료 코드 4), smoke 모드, artifact 저장, 다중 에피소드, 연속 3회 실행 후 서버 포트·프로세스·임시 프로필 누수 없음, Ctrl+Break 중단(Windows)

```powershell
python -m unittest discover -s tests/ai-runner -v
```

실제 게임으로 확인한 결과(smoke, 개발자 빌드)는 PR·이슈 #20 보고에 별도로 적습니다.
