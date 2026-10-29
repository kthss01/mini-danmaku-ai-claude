# AI 브라우저 통합 검증 도구

담당: 세션 5 · 이슈 [#24](https://github.com/kthss01/mini-danmaku-ai-claude/issues/24). 설정은 [docs/AI_SETUP.md](../../docs/AI_SETUP.md), QA 항목과 결과는 [docs/ai/QA.md](../../docs/ai/QA.md)다.

**여기 있는 것은 mock·fixture 검증이다. 실제 게임 결과가 아니며 클리어 증거가 아니다.**

## 구성

- `mock-adapter.js`: 브리지 어댑터(`ai/bridge/taisei-ai-bridge.mjs`)와 같은 이름·반환 형식의 가짜 어댑터. 소유권 전이, 제출 상태 코드, 입력 해제(슬롯 폐기)를 CONTRACT v1 4~6절대로 흉내 낸다. `sim.*`으로 일시정지·사용자 키·게임 오버·스테이지 종료·재시작·브리지 오류를 재현한다. 브라우저에서는 `?ai=mock`일 때 셸이 `game/ai-mock-adapter.js`로 불러 쓴다(패키징하지 않는다).
- `host.test.mjs`: `web/game/ai-host.js` 단위 검증(mock 어댑터 사용).
- `bridge-compat.test.mjs`: 호스트와 **실제 어댑터 코드**(세션 2, `ai/bridge/`)의 접합 검증. 어댑터와 `tests/ai-bridge/mock-module.mjs`가 main에 없으면 건너뛴다.

## 실행

```powershell
node --test tests/ai-integration/*.test.mjs
```

`node --test tests/ai-integration/`(디렉터리)는 Node 24에서 모듈로 해석되어 실패하므로 파일 글롭을 쓴다.
