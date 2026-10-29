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

모두 `EMSCRIPTEN_KEEPALIVE`이고 `src/meson.build`의 `EXPORTED_FUNCTIONS`에 `_taisei_ai_*`를 더한다. `EXPORTED_RUNTIME_METHODS`에는 `HEAPU8`을 더한다. Emscripten은 힙이 늘 때마다 `Module.HEAPU8`을 새 뷰로 바꾸므로 어댑터는 `Module.HEAPU8.buffer`(`Module.wasmMemory`가 있으면 그쪽)로 현재 `ArrayBuffer`를 얻는다.

| 함수 | 반환 | 설명 |
| --- | --- | --- |
| `taisei_ai_abi_version()` | int | 1 |
| `taisei_ai_layout()`, `taisei_ai_layout_size()` | 포인터, 바이트 수 | 레이아웃 JSON (UTF-8, NUL 제외 길이) |
| `taisei_ai_set_observe(int)` | — | 관측 캡처 켜기/끄기 |
| `taisei_ai_enable()`, `taisei_ai_resume()` | 0=ok, 1=not_playing, 2=noop | 4.1절 |
| `taisei_ai_suspend(int reason)`, `taisei_ai_disable(int reason)` | — | 사유 코드는 CONTRACT 4.2절 |
| `taisei_ai_submit(int ep, int target, int hold, int edges)` | 0~6 | CONTRACT 6.2절 상태 코드 |
| `taisei_ai_set_seed(int lo, int hi, int sticky)`, `taisei_ai_clear_seed()` | — | 시드 예약 |
| `taisei_ai_set_missing_limit(int n)` | — | 연속 누락 허용 틱 수(기본 30, 0=허용 없음, 음수=기본). 넘으면 `ai_suspended(action_timeout)` |
| `taisei_ai_set_limits(int bullets, int lasers, int segs, int enemies)` | — | 캡처가 담는 개수 상한을 정적 최대 이하로 낮춘다(0 이하=최대로 복원). overflow 경로를 작은 숫자로 시험하는 용도 |
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

실제 게임(웹 빌드, Stage 1 Normal, 레이무, 스테이지 시작부터 700프레임)에서 잰 값이다. 조건: 내장 브라우저(Chromium)의 **숨겨진 패널**에서 실행했고 PC CPU 부하가 높았다. `performance.now()`·`emscripten_get_now()`의 해상도는 0.1 ms다. 그래서 0.1 ms 아래는 "측정 한계 아래"로 읽는다.

| 항목 | 값 | 조건 |
| --- | --- | --- |
| 관측 구조체 크기 | **451,148 B** (정적, 시작 때 한 번 할당) | 탄 4096, 레이저 64, 구간 4096, 적 256 |
| C 캡처 시간(콜백 제외) | 평균 **0.004 ms**, 최대 **0.2 ms**, p50/p95 0 ms(해상도 아래) | 700프레임, 탄 최대 32개(p50 4, p95 30), 적 최대 약 13개 |
| C 캡처 시간, 탄이 더 많은 구간 | 탄 ≥ 60인 351프레임(최대 141): 평균 **0.027 ms**, p95 0.1 ms, 최대 0.3 ms. 탄 < 60인 1239프레임: 평균 0.009 ms | Stage Practice Stage 1 Normal, 1590프레임. 타이머 해상도 0.1 ms라서 개별 값은 0.1 ms 단위로만 읽힌다 |
| JS 읽기 `read()` | p50 0 ms, p95 0.1 ms | 같은 구간 |
| JS 복사 `snapshot()` | p50 0.1 ms, p95 0.2 ms | 같은 구간(탄 ≤ 32) |
| JS 복사 `snapshot()`, 최악 크기 | p50 0.2 ms, p95 0.4 ms, 최대 0.8 ms | 실제 wasm 메모리에 개수 필드만 탄 4096·구간 4096·적 256으로 써 놓고 복사. **C 캡처가 아니라 JS 복사 비용**이다 |
| 실측 최대 개수 | 탄 **504**(Stage Practice Stage 1 Normal, 중간보스 전후 약 9000프레임 구간), 적 약 13, 레이저 0 | 최대 4096은 이 표본의 8배다. 다른 스테이지·난이도는 미측정이라 "전 스테이지 2배 이상" 원칙은 **확인하지 못했다** |
| 브리지 꺼짐 상태의 프레임 시간 증가 | (미측정) | 꺼진 상태는 훅 지점 분기만 늘어난다 |

**"측정 한계 아래"를 "무시할 수 있다"로 일반화하지 않는다.** 위 값은 탄 최대 141개 표본, 해상도 0.1 ms의 타이머, 숨겨진 패널에서 잰 것이다. 탄 504개 구간은 존재를 확인했지만 그 프레임의 캡처 시간은 기록하지 못했다. 캡처는 탄·적·구간 수에 선형이고 탄마다 약 21개 필드를 쓰므로(탄 4096개면 쓰기 약 8.6만 회) 고밀도에서는 이 값이 커진다. 탄 수에 대한 평균 비용이 대략 탄 60개 이상에서 0.009 ms → 0.027 ms로 늘어난 것이 관측된 전부다. 고난이도·후반 스테이지 실측은 후속 과제다.

## 8. 검증 기록

검증한 fork 머리: 대부분 `a5db15ff`(master `1d4b468d` 위). 이후 fork master의 #3(자동 발사 기본)·#4(한국어)를 병합한 `f5511353`으로 다시 빌드해 스테이지 진입, 입력 1프레임 적용, 시드 주입, 메뉴 재시작을 다시 확인했다. 병합 변경은 `src/config.h`와 `po/ko.po`뿐이고 브리지 코드와 겹치지 않는다. 일시정지·사용자 키·리플레이 재생은 `a5db15ff` 빌드에서만 확인했다.

"fixture"는 가짜 Module로 어댑터 로직만 본 것이고, "실제 게임"은 이 문서의 fork 브랜치로 만든 웹 빌드를 내장 브라우저에서 돌린 것이다. 키 입력은 **DOM 키 이벤트**로 보냈다(실제 키보드 입력이 아니다). 증거 상세는 [tests/ai-bridge/evidence/2026-10-30-real-game.md](../../tests/ai-bridge/evidence/2026-10-30-real-game.md).

| 구분 | 항목 | 결과 |
| --- | --- | --- |
| fixture | 어댑터 단위 테스트 17건 (`node --test tests/ai-bridge/bridge.test.mjs`) | 통과 |
| 실제 게임 | 실제 WASM의 레이아웃이 계약 필드를 모두 갖췄는가(`createBridge`의 `validateLayout`) | **통과** |
| 실제 게임 | 관측과 화면 일치 | **일치**(Stage 1 Normal). 관측 좌표로 겹쳐 그린 오버레이가 탄·적 스프라이트와 맞고, HUD의 잔기·그레이즈·파워가 관측과 같다. 증거 이미지는 evidence 폴더. 레이저 구간은 Stage 1에 레이저가 없어 **미검증** |
| 실제 게임 | 입력이 1프레임 뒤에 적용 | **통과**. 틱 F에서 낸 hold가 틱 F+1의 `inputflags`와 180쌍 모두 일치(`a5db15ff`), 병합 빌드(`f5511353`)에서 300쌍 중 299쌍 일치. 나머지 1쌍은 사망 처리 틱(`hit_pending → dead`)에서 원본 `player_realdeath`가 이동 비트를 지우는 규칙 때문이다(CONTRACT 6.2절). `missing` 0 |
| 실제 게임 | 이동·경계 | 틱당 −5.625으로 이동, x=16에서 멈춤(`PLR_MIN_BORDER_DIST`) |
| 실제 게임 | 재시작 후 상태 초기화 | **통과**. `request_restart` → `episode_id` +1, `ai_suspended(restart)`, `act_*`·`p_ev_*` 0, `inputflags` 0, 탄 0. 메뉴의 "Restart the Game"도 `episode_id` +1, 시드 갱신(이때 사유는 `game_over` 그대로: 원본이 `stage_finish` 없이 `GAMEOVER_RESTART`를 직접 설정한다) |
| 실제 게임 | AI 해제 시 입력 해제 | **통과**. `disable` 뒤 `inputflags` 0, 일시정지 후 `ai_suspended`에서 재개 시 `inputflags` 0 |
| 실제 게임 | 일시정지 | **통과**. Esc → `ai_suspended(pause)`, `status.paused` 1. 풀어도 `ai_suspended` 유지(자동 재활성화 없음) |
| 실제 게임 | `ai_active` 중 사용자 키 | **통과**. 방향키 → `manual(user_input)`, 이후 `inputflags`는 물리 키(LEFT)와 같고 뗀 뒤 0 |
| 실제 게임 | 게임오버 메뉴에서 `enable` | `ai_suspended(not_playing)`, `resume`도 `not_playing` |
| 실제 게임 | 시드 주입 | **통과**. 관측 `seed_lo/hi`와 `seed_source=1`이 지정값과 일치 |
| 실제 게임 | 결정성(같은 시드·같은 액션 열) | 같은 페이지 세션 안에서 **일치**: 시드 12345를 첫 페이지에서 3회(프레임 100/200/300 해시 동일)·2회(400/700 동일, 사망 프레임 885 동일), 다시 연 페이지에서 2회(5개 체크포인트 동일). 시드 777은 700프레임에서 해시가 달라지고 사망 프레임도 다름(885 대 882). 두 페이지의 해시 값은 서로 다르다(캐릭터·샷 선택 경로가 달랐을 수 있다). 해시 대상은 플레이어 위치·잔기·그레이즈·탄·적의 위치. **한계:** 같은 페이지 세션 안의 반복이고, `EV_CHECK_DESYNC`는 확인하지 않았다. 다른 페이지 세션과는 비교하지 않았다 |
| 실제 게임 | AI 입력의 리플레이 기록·재생 | **통과**. AI가 낸 한 에피소드를 게임 메뉴로 저장하고 Replays에서 재생했을 때(`replay_mode` 1, `seed_source` 2, 시드 12345) 프레임 100/200/300/400/700의 상태 해시가 AI 실행과 모두 같다 |
| 실제 게임 | 수동 플레이 회귀(브리지 비활성) | 관측을 켠 상태의 수동 입력(방향키)과 메뉴 조작은 정상. **관측까지 끈 상태의 별도 회귀 비교는 하지 않았다** |
| 실제 게임 | 연속 누락 만료(Codex 지적 반영, `7d332b69` 빌드) | **통과**. 한도 6으로 낮춘 상태에서 3틱 누락은 허용(`act_missing_run` 1→3, 적용 후 0으로 복귀, `ai_active` 유지), 이어 연속 누락이 한도를 넘는 틱에 `ai_suspended(action_timeout)`로 바뀌고 그 틱 `inputflags`가 0으로 풀렸다. 첫 관측 전에는 세지 않는다(첫 관측의 `act_missing_run`=0). 새 에피소드는 `act_missing`·`act_missing_run`·`act_applied`·`p_ev_bomb`가 0으로 돌아가고 한도(30)는 유지된다. 콜백을 제거해 둔 채 `ai_active`를 방치하면 한도(30틱) 뒤 `action_timeout`이 된 것도 확인했다 |
| 실제 게임 | 엣지 1회 소비 | **통과**. `BOMB` 엣지를 한 번 낸 뒤 4틱 누락(한도 6 이내) 동안 `p_ev_bomb`가 12→13으로 한 번만 오르고 봄이 3→2로 한 번만 줄었다(누락 틱에 반복되지 않음) |
| 실제 게임 | overflow 경계(`taisei_ai_set_limits`로 상한을 낮춘 실행) | **부분 확인**. 탄 상한 5, 실제 총 65개에서 `n_bullets`=5, `total_bullets`=65, `overflow`=1(탄), 남은 탄의 최대 거리가 약 276.6이고 18프레임 뒤 상한 없는 캡처의 5번째 가까운 탄 거리 241.9와 같은 속도로 줄어드는 값이라 "가까운 순" 선택과 일치(같은 프레임 비교는 못 함). **적(`n_enemies`)과 레이저·구간 상한 초과 경계는 해당 개체가 없어서 확인하지 못했다** |
| 실제 게임 | 대화 넘김(`hold.SKIP`) | **통과**. 보스 전 대화 중 `hold.SHOT`만으로는 넘어가지 않고(`SHOT`은 `inputflags`이고 대화 넘김은 `EV_PRESS`/`INFLAG_SKIP`이다) `SKIP`을 더하면 넘어가 보스 체력 26000의 첫 공격이 시작됐다 |
| 실제 게임 | 컨티뉴 후 재개 | 게임오버 메뉴 → 컨티뉴 → `p_continues_used` 1로 오르고 `resume()`으로 `ai_active` 복귀 |
| 실제 게임 | **레이저**(`active`·`width`·`seg_start/count`·끝점·`ra/rb`) | **미검증**. Stage 1에서 레이저는 보스 스펠(`snow_halation`)에만 나오는데 내장 브라우저 숨겨진 패널에서 게임이 크게 느려져(보스 전 대화 뒤 수 분에 수백 프레임) 도달하지 못했다. 원본 충돌 데이터와의 비교는 하지 않았다 |
| 실제 게임 | Stage 2 이후 | **미검증** |
