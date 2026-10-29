# AI 실행 환경 설정 (브라우저 통합)

담당: 세션 5 · 이슈 [#24](https://github.com/kthss01/mini-danmaku-ai-claude/issues/24) · 부모 [#19](https://github.com/kthss01/mini-danmaku-ai-claude/issues/19)

웹 셸(`web/game/`)에서 수동 플레이와 AI 플레이를 오가는 방법과 통합 구성을 정리한다. QA 항목과 결과는 [docs/ai/QA.md](ai/QA.md), 셸 일반은 [docs/web/SHELL.md](web/SHELL.md)를 본다.

> **현재 상태(초안).** 셸의 AI 연결(호스트 API·모드 UI)은 mock 어댑터로만 검증했다. 실제 브리지(세션 2)와 정책(세션 3)이 main에 들어오고 fork C 구현이 gitlink로 반영된 뒤에야 실제 게임 연결을 확인할 수 있다. 아직 확인하지 않은 부분은 "(대기)"로 표시한다. mock 성공은 실제 게임 성공이 아니다.

## 1. 구성

```text
브라우저 페이지(web/game/index.html)
├─ 웹 셸 shell.js ........ 모드 UI(수동 / AI 동작 중 / AI 정지), 상태·오류 표시, 포커스 정책
├─ AI 호스트 ai-host.js .. window.taiseiAI: enable / suspend / resume / disable / state / onEvent ...
│    ├─ 어댑터(브리지)  ai/bridge/taisei-ai-bridge.mjs   (세션 2 소유, CONTRACT 10절)
│    └─ 정책 번들       ai/policies/<id>/index.js          (세션 3 소유, taisei.ai.policy/0)
└─ taisei.wasm + fork 브리지(C) ... 관측 캡처·입력 적용·owner_state (세션 2)
```

- 소유권(`manual` / `ai_active` / `ai_suspended`)의 진실은 브리지의 `owner_state`다. 셸은 보여주고 전환을 요청할 뿐이다([CONTRACT 4절](ai/CONTRACT.md), 세션 2 계약 PR 머지 후 링크가 열린다).
- 정책은 페이지 안에서 실행한다(#20 v0.1 A안). 판단은 동기 콜백(`Module.taiseiAIOnFrame`)으로 프레임마다 불리며 LLM API는 호출하지 않는다.
- 게임 규칙·판정·속도·잔기·봄은 바꾸지 않는다. AI는 사람의 키와 같은 `player_event` 경로로 입력한다(리플레이에 기록, CONTRACT Q2).

## 2. URL 파라미터

| 파라미터 | 동작 |
| --- | --- |
| (없음) | 브리지가 게임에 있으면 자동으로 연결하고 AI 패널을 보여준다. 없으면 패널이 나타나지 않아 수동 플레이는 그대로다 |
| `?ai=0` 또는 `off` | AI 연결을 시도하지 않는다 |
| `?ai=1` | 브리지가 없어도 패널을 보여주고 사용 불가 사유를 알린다 |
| `?ai=mock` | 검증용 mock 어댑터를 쓴다(실제 게임 입력이 아니다, 패널에 "mock 어댑터" 경고). 프로덕션 셸에는 mock 참조가 없고, 검증용 사이트가 `game/shell-config.js`에서 `aiMockScript: 'ai-mock-adapter.js'`를 지정하고 `tests/ai-integration/mock-adapter.js`를 그 이름으로 `game/`에 두어야 한다 |
| `?policy=<id>` | `ai/policies/<id>/index.js` 정책 번들을 불러온다 |

## 3. 호스트 API `window.taiseiAI`

실행기(세션 1, Playwright)와 셸 UI가 같은 경로를 쓴다. 스키마 `taisei.ai.host/0`.

| 메서드 | 반환 | 설명 |
| --- | --- | --- |
| `ready` (Promise) | 상태 | 셸의 AI 초기화(브리지·빌드 정보·정책 불러오기)가 끝나면 settle. 첫 프레임 이후에 시작한다 |
| `loadPolicy(idOrUrl, config?)` | Promise | 정책 번들을 불러온다. `default_config`와 `config`를 합친다 |
| `enable()` | `'ok'` · `'not_playing'` · `'noop'` · `'unavailable'` · `'no_policy'` · `'policy_error'` · `'bridge_error'` | `manual → ai_active`. 진행 중인 스테이지가 아니면 `ai_suspended`(`not_playing`) |
| `suspend(reason='host_request')` | `'ok'` · `'unavailable'` | `ai_active → ai_suspended`. 입력은 즉시 해제된다 |
| `resume()` | `enable()`과 같다 | `ai_suspended → ai_active`. **자동 재개는 없다.** 일시정지·포커스 상실 뒤에는 이 호출이 필요하다 |
| `disable(reason='host_request')` | `'ok'` · `'unavailable'` | 임의 → `manual` |
| `notifyFocusLost()` | `'ok'` · `'noop'` | 창 포커스 상실·탭 숨김. `ai_active`일 때만 `ai_suspended`(`focus_lost`)로 올린다 |
| `state()` | 객체 | `mode`, `reason`, `reasonInfo`, `inStage`, `paused`, `episodeId`, `lastFrame`, `buildFlavor`, `rulesPreserved`, `policy`, `warnings`, `lastError`, `decision`(p50/p95/최대 판단 시간), `shotSemantics` 등 |
| `onEvent(cb)` | 해제 함수 | `{type: 'transition' \| 'error' \| 'attach' \| 'policy' \| 'build' …}` |
| `getAdapter()` | 어댑터 | 읽기(`read`/`snapshot`/`state`) 용도. 소유권은 위 메서드로 바꾼다 |
| `decisionStats()` | 객체 | 판단 시간과 제출 집계(아래 "통계 범위" 참조) |

### 정책 action 형식(`taisei.ai.act/1`)과 검사

호스트는 정책 `decide(obs)`가 **동기**로 돌려준 `{ hold, edges, request }`만 받는다. `hold`는 0~127 정수 비트(UP=1 DOWN=2 LEFT=4 RIGHT=8 FOCUS=16 SHOT=32 SKIP=64), `edges`는 0~3 정수 비트(BOMB=1 SPECIAL=2)이며 둘 다 필수다. 어댑터 `ctl.submit({ hold, edges })`에 **그대로** 전달한다(예전 `bomb`/`special` 필드는 받지 않는다). 이 규칙을 어기면 호스트는 그 프레임에 제출하지 않고 `manual`(`policy_error`)로 중단한다.

- 거부 대상: Promise(async 정책, 거부된 Promise는 미처리 오류가 남지 않게 흡수), 배열·문자열, 범위 밖·소수 비트, `edges` 누락, 알 수 없는 `request.type`.
- `request.release`: 그 프레임에 `submit({hold:0, edges:0})`(소유권 유지, 제어 중단이며 생존 보장 아님). `request.suspend`: `submit({hold:0, edges:0})` 뒤 `suspend(reason)`. 허용 사유(`focus_lost`·`dialog`·`host_request`·`policy_error`·`policy_deadline`·`observation_invalid`) 밖이면 `policy_deadline`.
- `reset(why)` 실패: `enable`은 `policy_error`를 돌려주고 제어를 시작하지 않으며, `resume`·에피소드 경계에서의 실패는 입력·대기 엣지를 해제하고 `manual`(`policy_error`)로 중단한다. 실패한 reset 뒤에는 `decide`도 제출도 하지 않는다.
- 정책 교체: AI가 `ai_active`/`ai_suspended`인 동안 `setPolicy`/`setPolicyModule`로 정책을 바꾸거나 없애면 **먼저 `disable('host_request')`로 입력을 해제하고 `manual`로 전환**한다. 새 정책은 `enable()`을 명시적으로 불러야 시작한다(이전 입력을 유지하지 않는다). dispose → init → reset 순서는 `enable`에서 일어난다. 모듈 `init` 실패는 `enable()`이 `policy_error`로 돌려주고 수동을 유지한다.
- `ai_active`인데 정책이 없는 프레임이 오면(방어 경로) 입력을 해제하고 `manual`(`policy_error`)로 전환한다.

### 통계 범위(`decisionStats()`)

| 필드 | 범위 |
| --- | --- |
| `p50_ms`, `p95_ms` | 최근 `window_size`(512)개 표본. `window_samples`가 실제 표본 수 |
| `count`, `mean_ms`, `max_ms`, `over_frame` | 정책을 지정(`setPolicy*`)한 뒤 누적. 위 두 분포와 같지 않다 |
| `frame_budget_ms` | 16.67 — **한 프레임 전체** 기준이다. 정책 자체의 판단 예산(정책 `config.budget_ms`, 초안 4 ms)과 다르며, 정책 내부 예산 초과는 정책 `stats()`·`meta.over_budget`을 본다 |
| `submit.attempted / accepted / rejected / by_status / last_rejected` | 제출 시도와 결과 상태(`accepted`·`stale`·`dup`·`wrong_episode`·`not_active`·`future`·`no_stage`·`exception`). 거부는 집계만 하고 소유권을 바꾸지 않는다. 평가의 `quality.action_sync`는 어댑터 카운터를 쓰고 이 값은 호스트 쪽 보조 증거다 |
| `releases`, `policy_suspends` | 정책 요청 횟수 |

사유 코드 문자열은 CONTRACT 4.2절 15종이며 UI, `owner_state` 전환, 평가의 `run.reason_code`가 같은 값을 쓴다.

### 실행기가 쓰는 순서(제안, 세션 1과 확정 대기)

```js
await page.evaluate(() => taiseiAI.ready);                  // 첫 프레임 이후
await page.evaluate((id) => taiseiAI.loadPolicy(id), policyId);
const r = await page.evaluate(() => taiseiAI.enable());     // 'ok' 확인
// 에피소드 진행 중: taiseiAI.state() 폴링 또는 onEvent
await page.evaluate(() => taiseiAI.disable('host_request')); // 정리: 입력 전부 해제
```

## 4. 모드 UI 동작

| 상황 | 모드 | 사유 |
| --- | --- | --- |
| AI 시작 버튼 | `ai_active` | — (스테이지가 아니면 `ai_suspended` / `not_playing`) |
| 정지 버튼 | `ai_suspended` | `host_request` |
| 수동으로 버튼 | `manual` | `host_request` |
| AI 동작 중 사용자가 게임 키를 누름 | `manual` | `user_input` (입력은 섞지 않는다) |
| 일시정지(Esc) | `ai_suspended` | `pause` (풀려도 자동 재개 없음) |
| 창 포커스 상실·탭 숨김 | `ai_suspended` | `focus_lost` (돌아와도 자동 재개 없음) |
| 게임 오버·스테이지 종료·재시작 | `ai_suspended` | `game_over` · `stage_end` · `restart` |
| 정책 예외·잘못된 액션 | `manual` | `policy_error` |
| 브리지 오류, 게임 모듈 abort | `manual` | `bridge_error` |

- AI 패널은 화면 왼쪽 아래에 있고 마우스를 올리거나 주의가 필요한 사유(`warn`/`error`)일 때 또렷해진다. `▾`로 정책·빌드·판단 시간·공격 입력 설명을 연다.
- 버튼을 누른 뒤에는 포커스를 게임 화면으로 돌려 키 입력이 계속 게임에 전달되게 한다.

## 5. 개발자 빌드 경고

`build-info.json`(서빙 루트, 게임 페이지 기준 `../build-info.json`)의 `build.flavor`로 빌드 종류를 판단한다.

| 값 | 표시 |
| --- | --- |
| `developer` | "개발자 빌드입니다. 원본 규칙 보존이 확정되지 않았습니다(검증 전)…" 경고. `rulesPreserved: unverified`. 결과를 원래 규칙의 클리어 증거로 쓰지 않는다(#20 v0.1 B) |
| 없음(릴리스 산출물은 flavor를 기록하지 않는다) | `release`로 본다. 경고 없음 |
| 파일을 읽지 못함 | `unknown`. "빌드 종류를 확인하지 못했습니다" 경고 |

## 6. 공격 입력과 `shot_inverted` (자동 발사)

웹 빌드는 `CONFIG_SHOT_INVERTED`(`shot_inverted`) 기본값이 1이다(PR #40, fork PR kthss01/taisei#3). 켜져 있으면 `Z`를 누르지 않을 때 쏘고 누르는 동안 멈춘다. 게임 옵션 "기본 공격 상태"(Shoot by default)에서 끌 수 있다.

| 모드 | 의미 |
| --- | --- |
| 수동 | 반전은 **물리 키**에만 적용된다. 설정이 켜져 있으면 `Z` 뗌 = 발사, `Z` 누름 = 멈춤 |
| AI | 액션의 `hold.SHOT`은 반전과 무관하게 **항상 "공격 중"**이다(CONTRACT 6.1). 정책은 `SHOT` 비트를 켜 두면 쏜다 |

이미 저장된 브라우저 설정에는 `shot_inverted = 0`이 남아 있을 수 있다. AI 입력은 영향을 받지 않지만 **수동 모드 확인 결과를 기록할 때 이 값을 함께 적는다.** 현재 브리지 상태 블록에는 이 설정값이 없어서, 평가가 값을 읽어 기록하려면 세션 2가 읽기 전용 필드(예: `cfg_shot_inverted`)를 추가해야 한다(#24에 요청).

## 7. 검증용 mock

실제 게임·브리지 없이 UI와 전환 로직을 확인한다. **결과는 mock 성공이며 클리어 증거가 아니다.**

```powershell
# 호스트 로직 단위 검증(어댑터 파일이 main에 있으면 실제 어댑터 호환 검증도 함께 실행)
node --test tests/ai-integration/*.test.mjs
```

화면 확인(무거운 빌드 없이): 이미 빌드된 `build/web/site` 사본을 자기 출력 폴더에 복사하고, 바꾼 셸 파일(`web/game/index.html`, `shell.js`, `shell.css`, `shell-config.js`, `ai-host.js`)과 `tests/ai-integration/mock-adapter.js`(`game/ai-mock-adapter.js`로 이름 변경)만 덮어쓴 뒤 `game/shell-config.js`에 `aiMockScript: 'ai-mock-adapter.js'`를 더하고 `scripts/serve-web.py --root <출력 폴더>`로 열어 `game/index.html?ai=mock`을 연다. 덮어쓴 사본에도 `python scripts/check-web-assets.py --root <출력 폴더>`를 돌려 정적 검사를 통과하는지 확인한다(셸이 참조하는 파일이 사이트에 있어야 한다). 원본 산출물 폴더는 바꾸지 않는다. 기록에는 어떤 산출물에 덮어썼는지 적는다.

mock 모드에서는 키보드의 게임 키가 사용자 키 전환(`user_input`)을, `Esc`가 일시정지(`pause`)를 흉내 낸다. 실제 게임에서는 브리지(C)가 처리한다. 콘솔에서 `taiseiAIMockAdapter.sim.*`로 일시정지·게임 오버·스테이지 종료·브리지 오류를 재현할 수 있다.

## 8. 패키징·서빙

| 항목 | 규칙 |
| --- | --- |
| 어댑터 | `ai/bridge/taisei-ai-bridge.mjs` → `site/game/ai/bridge/` (`scripts/build-web.ps1`, PR #49). 셸 기본값 `aiBridgeUrl`과 같다 |
| 정책 | `ai/policies/**` → `site/game/ai/policies/<id>/` (`aiPolicyBase`, 진입 파일 `aiPolicyEntry`) |
| 서버 MIME | `.mjs`는 `text/javascript`여야 모듈로 불러온다. `scripts/serve-web.py`는 이미 그렇게 고정되어 있다 |
| 셸 파일 | `web/game/*`는 `build-web.ps1`이 `site/game/`에 통째로 복사한다(`ai-host.js` 포함). mock 어댑터는 패키징하지 않는다 |
| 정적 검사 | `check-web-assets.py`는 `shell.js`의 `.js`/`.mjs` 문자열 리터럴을 페이지 기준 파일 참조로 본다. 사이트에 없는 파일을 가리키는 리터럴(예: mock 경로, `/`로 시작하는 조각)을 넣으면 CI가 실패한다 |

위치가 달라지면 `web/game/shell-config.js`만 고친다.

## 9. 문제 해결

| 증상 | 원인·조치 |
| --- | --- |
| 패널이 아예 없다 | 정상(브리지 없음). `?ai=1`로 사유를 확인한다 |
| "이 게임 빌드에는 AI 브리지가 없습니다" | 게임 wasm에 `taisei_ai_*` 내보내기가 없다. 브리지가 들어간 빌드(세션 1 개발자 빌드)를 쓴다 |
| "AI 브리지를 불러오지 못했습니다" | 어댑터 파일이 `aiBridgeUrl` 위치에 없거나 ABI·레이아웃이 계약과 다르다. 콘솔과 로그 패널의 `[AI]` 줄을 본다 |
| "정책이 없습니다" | `?policy=<id>`를 지정하거나 `taiseiAI.loadPolicy(id)`를 호출한다 |
| 일시정지나 창 전환 뒤 AI가 멈춰 있다 | 설계대로다. **재개**를 누른다 |
