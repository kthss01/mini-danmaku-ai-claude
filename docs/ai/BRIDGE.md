# AI 브리지 구현·제약·측정 비용

담당 이슈: [#21](https://github.com/kthss01/mini-danmaku-ai-claude/issues/21) · 계약: [CONTRACT.md](CONTRACT.md) (이 문서는 구현 세부이고 다른 세션이 의존하는 값은 계약에 있다)
기준 소스: fork `kthss01/taisei` `master` `1d4b468d`

## 1. 구성과 PR 분리

| 구분 | 위치 | PR |
| --- | --- | --- |
| 계약·문서 | `docs/ai/CONTRACT.md`, `docs/ai/BRIDGE.md` | 메인 계약 PR (`feat/ai-bridge`) |
| JS 어댑터 | `ai/bridge/taisei-ai-bridge.mjs` | 메인 계약 PR |
| 어댑터 fixture 테스트 | `tests/ai-bridge/` | 메인 계약 PR |
| C 브리지 | fork `src/ai_bridge.c`·`ai_bridge.h`, 훅 4곳(`stage.c`, `player.c`, `meson.build`, `src/meson.build`) | fork PR (`feat/ai-bridge`) |
| `game/taisei` gitlink 갱신 | — | 세션 1(#20)이 fork 머지 뒤 갱신. 이 세션은 바꾸지 않는다 |

테스트 구분: `tests/ai-bridge/`는 **가짜 Module로 어댑터 로직만** 검증한다(fixture). 실제 게임 검증은 8절에 따로 적는다. 둘을 섞어 보고하지 않는다.

## 2. C 브리지 (fork)

### 2.1 훅 지점

| 위치 | 동작 |
| --- | --- |
| `stage_logic_frame`, `cosched_run_tasks`·`stage_replay_sync` 뒤, `global.frames++` 앞 | 관측 캡처(`taisei_ai_capture`). 비활성이면 분기 1개 |
| `stage_input` (`process_input`의 비-리플레이 경로) | 소유권이 `ai_active`이면 이벤트 필터(사용자 키 감지)와 AI 입력 적용 |
| `player_fix_input` | `ai_active`이면 물리 키 대신 AI `hold`로 `newflags`를 만든다. 결과는 기존과 같이 `player_event(EV_INFLAGS)`로 나가 리플레이에 기록된다 |
| `_stage_enter` | `rng_seed` 직전 시드 주입, 직후 `episode_id` 증가·카운터 초기화 |
| `stage_finish`, `stage_pause`, `stage_gameover` | 자동 `ai_suspended` 전환 |
| `player_death`·`player_realdeath`·`stats_track_bomb_used`·`player_event`(치트) | 이벤트 카운터 |

리플레이 재생 경로(`replay_input`)는 `player_fix_input`을 부르지 않는다. 그래서 재생 중에는 AI 입력이 적용되지 않는다(`replay_mode = 1`, `enable` → `not_playing`).

### 2.2 내보내는 함수

모두 `EMSCRIPTEN_KEEPALIVE`이고 `src/meson.build`의 `EXPORTED_FUNCTIONS`에 `_taisei_ai_*`를 더한다. `EXPORTED_RUNTIME_METHODS`에는 `wasmMemory`가 없으면 `HEAPU8`을 더해 어댑터가 현재 `ArrayBuffer`를 얻을 수 있게 한다.

| 함수 | 반환 | 설명 |
| --- | --- | --- |
| `taisei_ai_abi_version()` | int | 1 |
| `taisei_ai_layout()`, `taisei_ai_layout_size()` | 포인터, 바이트 수 | 레이아웃 JSON (UTF-8, NUL 제외 길이) |
| `taisei_ai_set_observe(int)` | — | 관측 캡처 켜기/끄기 |
| `taisei_ai_enable()`, `taisei_ai_resume()` | 0=ok, 1=not_playing, 2=noop | 4.1절 |
| `taisei_ai_suspend(int reason)`, `taisei_ai_disable(int reason)` | — | 사유 코드는 CONTRACT 4.2절 |
| `taisei_ai_submit(int ep, int target, int hold, int edges)` | 0~6 | CONTRACT 6.2절 상태 코드 |
| `taisei_ai_set_seed(int lo, int hi, int sticky)`, `taisei_ai_clear_seed()` | — | 시드 예약 |
| `taisei_ai_request_restart()` | — | 다음 `process_input`에서 `stage_finish(GAMEOVER_RESTART)` |

호스트 콜백(선택): `Module.taiseiAIOnFrame(frame, episode_id)`(캡처 직후), `Module.taiseiAIOnEvent(kind, state, reason)`(전환 직후). 둘 다 `EM_ASM`으로 있을 때만 부른다.

### 2.3 비활성 기본값과 회귀

`ai_active`가 한 번도 켜지지 않고 `observe`도 꺼진 상태에서는 게임 로직이 읽는 값이 원본과 같다. 추가되는 것은 위 훅 지점의 분기뿐이다. 수동 플레이 회귀는 8절에서 확인한다.

### 2.4 레이아웃 JSON 형식

```json
{
  "schema": "taisei.ai.obs/1", "abi": 1, "base": <관측 구조체의 wasm 주소>, "size": <바이트>,
  "i32":    { "offset": 0, "count": N, "fields": { "frame": 0, ... } },
  "f32":    { "offset": ..., "count": N, "fields": { "p_x": 0, ... } },
  "status": { "offset": ..., "count": N, "fields": { "in_stage": 0, ... } },
  "arrays": { "bullets": { "max": 4096, "count_field": "n_bullets",
                           "fields": { "id": {"type": "u32", "offset": ...}, ... } }, ... },
  "enums":  { "owner_reason": ["none", "pause", ...], "gameover": {...} }
}
```

`offset`은 `base` 기준 바이트이고 모두 4바이트 정렬이다. 필드 이름·형은 계약이고, 어댑터의 `validateLayout`이 이를 검사한다. 필드가 빠지거나 형이 다르면 `createBridge`가 `BridgeError('layout_mismatch')`를 던진다.

## 3. JS 어댑터 (`ai/bridge/taisei-ai-bridge.mjs`)

| 책임 | 구현 |
| --- | --- |
| 뷰 재생성 | `read`/`state`/`submit`마다 `wasmMemory.buffer`(없으면 `HEAPU8.buffer`)와 직전 버퍼를 `===`로 비교하고, 달라졌으면 모든 `TypedArray`를 새로 만든다 |
| 레이아웃 해석 | `taisei_ai_layout()` JSON만 믿는다. 오프셋을 하드코딩하지 않는다 |
| 읽기 | `read()`는 복사 없이 배열 뷰를 돌려주고(다음 캡처 전까지 유효) 객체를 재사용한다. 보관은 `snapshot()` |
| 동기 콜백 | `onFrame(cb)`가 `Module.taiseiAIOnFrame`을 설치한다. 콜백 예외는 `disable('policy_error')` + `takeErrors()` |
| 사용처 | 세션 5 셸, 세션 3 정책, 세션 1 실행기가 ES 모듈로 `import`한다. 사이트 패키징에 이 파일을 복사하는 일은 세션 1/5가 정한다(이 PR은 파일만 제공) |

실행: `node --test tests/ai-bridge/bridge.test.mjs` (Node 24, 외부 의존성 없음).

## 4. 지원하지 못하는 항목

CONTRACT 7절의 표가 기준이다. 요약: 시작(`start`), 프레임 스텝, 퀵세이브/로드 제어는 미지원. 레이저 구간은 한 틱 오차. 아이템·아군 탄·그레이즈 형상은 없다.

## 5. 기본 설정과의 상호작용

- **`SHOT_INVERTED`**: 웹 빌드는 `shot_inverted` 기본값이 1이다(`__EMSCRIPTEN__`, "Shoot by default"). 원본에서는 이 설정이 키 이벤트 처리(`stage_input_handler_gameplay`)와 `player_fix_input`의 **물리 키**에만 적용된다. 브리지의 `hold.SHOT`은 이 설정과 무관하게 항상 "공격 중"이다(AI는 반전을 거치지 않는다). 설정 값은 관측에 필요하지 않다. 이미 저장된 브라우저 설정이 0이어도 AI에는 영향이 없다.
- **`AUTO_SURGE`**: 켜져 있으면 원본 `player_fix_input`이 `EV_PRESS KEY_SPECIAL`을 만든다. AI가 `ai_active`일 때도 이 경로는 유지한다(게임 설정, 리플레이에 기록됨).
- **`FOCUS_LOSS_PAUSE`**: 창 포커스를 잃으면 원본이 `TE_GAME_PAUSE`를 보내 일시정지한다. 브리지는 이를 `pause`로 받는다. 호스트가 `blur`를 먼저 감지하면 `suspend('focus_lost')`를 부른다.
- **`SPELLSTAGE_AUTORESTART`**: 스펠 연습에서 잔기가 없을 때 메뉴 없이 재시작한다. `restart` 사유로 이어진다.

## 6. 제약·알려진 한계

1. 관측 값은 `float32`다. 원본은 `double`이다.
2. 탄 형상은 `PROJ_ENEMY`만. `PFLAG_NOCOLLISION` 탄은 제외한다.
3. 패턴 태스크가 중간에 `move`를 바꾸면 MoveParams 예측이 틀린다(CONTRACT 2.2절).
4. 레이저 구간은 틱 F의 `process_lasers` 시점이다(CONTRACT 1절).
5. `ai_active` 중 게임패드 아날로그 입력은 무시한다.
6. 동기 콜백이 느리면 게임 실시간이 느려진다(논리 프레임은 보존).
7. 퀵로드(연습 모드)는 `_stage_enter`를 다시 부르므로 `episode_id`가 올라간다.

## 7. 측정 비용

> 실제 게임에서 잰 값을 채우는 절이다. fork 검증 뒤에 기록한다. 지금은 비어 있다.

| 항목 | 값 | 조건 |
| --- | --- | --- |
| 관측 구조체 크기 | (미측정) | |
| 캡처 시간 p50/p95/max (탄 수별) | (미측정) | |
| JS 읽기·복사 시간 | (미측정) | |
| 전 스테이지 실측 최대 탄/레이저/구간/적 수 | (미측정) | |
| 브리지 꺼짐 상태의 프레임 시간 증가 | (미측정) | |

## 8. 검증 기록

> fork 구현 뒤에 채운다. "fixture"와 "실제 게임"을 구분해 적는다.

| 구분 | 항목 | 결과 |
| --- | --- | --- |
| fixture | 어댑터 단위 테스트 17건 (`node --test tests/ai-bridge/bridge.test.mjs`) | 통과 |
| 실제 게임 | 관측과 화면 일치 | (미검증) |
| 실제 게임 | 입력이 1프레임 뒤에 적용 | (미검증) |
| 실제 게임 | 재시작 후 상태 초기화 | (미검증) |
| 실제 게임 | AI 해제 시 입력 해제 | (미검증) |
| 실제 게임 | 수동 플레이 회귀(브리지 비활성) | (미검증) |
| 실제 게임 | AI 입력의 리플레이 기록·재생 | (미검증) |
| 실제 게임 | 같은 시드·같은 액션 열의 결정성 | (미검증, 확인 전에는 "재현 확인"이라 쓰지 않는다) |
