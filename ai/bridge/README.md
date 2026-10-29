# ai/bridge

Taisei(WASM) 관측·입력 브리지의 JS 어댑터입니다. 소유: 세션 2 (이슈 #21).

- `taisei-ai-bridge.mjs`: `createBridge(Module)`로 fork의 `taisei_ai_*` 함수를 감쌉니다. 계약은 [docs/ai/CONTRACT.md](../../docs/ai/CONTRACT.md), 구현은 [docs/ai/BRIDGE.md](../../docs/ai/BRIDGE.md)입니다.
- 테스트: `node --test tests/ai-bridge/bridge.test.mjs` (가짜 Module을 쓰는 fixture 테스트입니다. 실제 게임 결과가 아닙니다).

fork 쪽 C 구현이 머지되기 전에는 실제 게임에 연결되지 않습니다.
