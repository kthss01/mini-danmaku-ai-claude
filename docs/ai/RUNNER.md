# AI 실험 실행기: 실행·결과 저장 계약 v1

담당: AI 세션 1 ([#20](https://github.com/kthss01/mini-danmaku-ai-claude/issues/20)) · 부모: [#19](https://github.com/kthss01/mini-danmaku-ai-claude/issues/19)
기준: v0.1([#20 댓글](https://github.com/kthss01/mini-danmaku-ai-claude/issues/20#issuecomment-6375510106))에 세션 4 결과 스키마([#23](https://github.com/kthss01/mini-danmaku-ai-claude/issues/23#issuecomment-6375508642))와 세션 5 Q4([#24](https://github.com/kthss01/mini-danmaku-ai-claude/issues/24#issuecomment-6375572237))를 반영했다.

이 문서는 실행기가 **무엇을 하고, 무엇을 페이지(세션 2·3·5)와 평가(세션 4)에 맡기는지**를 정한다. 구현은 `scripts/ai/**`, 테스트는 `tests/ai-runner/**`다.

## 1. 검증 상태 (fixture와 실제를 구분한다)

| 구간 | 상태 | 근거 |
| --- | --- | --- |
| 실행기 흐름(인자 검증·run 폴더·서버·브라우저·감시·수집·정리·종료 코드) | **fixture 검증** | `tests/ai-runner`의 모의 페이지(`window.taiseiAI`를 흉내 냄). 실제 게임이 아니다 |
| 실제 게임 로드 | **실제 확인** | 개발자 빌드를 새 clone에서 만들고 `--mode smoke`로 셸이 `playing`에 이르는 것까지 확인 |
| 브리지 연동(`window.taiseiAI`, 에피소드 시작·종료 이벤트) | **미검증** | 세션 2 브리지·세션 5 호스트 API가 머지된 뒤 실제 연결 PR에서 확인 |
| 개발자 빌드의 원본 규칙 보존 | **미검증** | `rules_preserved: "unverified"`로 기록. 판정은 세션 4의 규칙 위반 감지와 별도 검증 |
| 게임 인자(`--sid` 등) 전달 | **미검증** | 셸이 `window.taiseiAIRun.game_args`를 `callMain(args)`로 넘겨야 한다(세션 5 조정) |
| 시드 지정 | **미지원** | 게임에 시드 지정 경로가 없다. `--seed`는 종료 코드 2 |

smoke 결과(`run.reason = smoke_duration`)와 fixture 결과는 평가 대상이 아니다(`run.evaluable = false`).

## 2. 사용법

```powershell
# 1) 빌드 (릴리스: build/web/site, 개발자: build/web-dev/site). Docker Desktop 필요, 빌드는 PC에서 한 번에 하나만.
.\scripts\setup-taisei.ps1
.\scripts\build-web.ps1                    # 릴리스. 기존 산출물과 출처 기록은 그대로
.\scripts\build-web.ps1 -Flavor developer  # 개발자 빌드(-Ddeveloper=true), 별도 폴더

# 2) 셸이 playing에 이르는지만 확인(브리지 없이)
python scripts/ai/run.py --mode smoke --smoke-duration-s 10

# 3) 브리지가 있는 빌드에서 실험(예: 스펠 연습 1개를 3회)
python scripts/ai/run.py --experiment-id spell-s1-easy --build-flavor developer --spell <id> --difficulty Easy `
    --policy avoid-v1 --episodes 3 --max-frames 3600 --wall-timeout-s 180

# 4) 테스트 (브라우저가 없으면 브라우저 테스트는 건너뜀)
python -m unittest discover -s tests/ai-runner -v
```

외부 패키지는 필요 없다(Python 표준 라이브러리 + 설치된 Chrome/Edge). Windows에서 `git worktree`로 만든 작업 폴더는 `game/taisei/.git`이 컨테이너 밖을 가리켜 Docker 빌드가 실패하므로, **빌드는 일반 clone에서** 한다.

## 3. 실행 인자

`--config FILE`(JSON, 키는 아래 옵션 이름의 `_` 표기)로 기본값을 줄 수 있고 명령줄이 우선한다. 알 수 없는 키는 오류다. 예시는 `configs/ai/`.

| 인자 | 기본 | 설명 |
| --- | --- | --- |
| `--experiment-id` | `adhoc` | 실험 식별자(영문·숫자·`._-`) |
| `--mode` | `bridge` | `bridge`: 브리지로 에피소드 실행. `smoke`: 브리지 없이 셸 확인 |
| `--policy` / `--policy-version` / `--policy-params` | `none` | 페이지 안에서 불러올 정책. 파라미터는 JSON 또는 파일 |
| `--difficulty` | `Easy` | Easy·Normal·Hard·Lunatic |
| `--shotmode` | (없음) | marisaA·marisaB·youmuA·youmuB |
| `--stage ID` / `--spell ID` | (없음) | 개발자 빌드 필요(`--sid`·`--diff` 인자 사용). 둘은 함께 쓸 수 없음 |
| `--seed N` | — | **미지원**, 지정하면 종료 코드 2 |
| `--max-frames` | 3600 | 논리 프레임 한도. 페이지(브리지)가 집행하고 `episode_end(frame_limit)`로 알린다 |
| `--wall-timeout-s` | 180 | 에피소드당 벽시계 한도. 실행기가 집행 |
| `--startup-timeout-s` | 120 | 페이지가 `playing`에 이르기까지 한도 |
| `--smoke-duration-s` | 5 | smoke 모드에서 `playing` 이후 지켜볼 시간 |
| `--episodes` | 1 | 연속 에피소드 수(에피소드마다 새 브라우저·새 프로필) |
| `--build-flavor` | `release` | 사용할 빌드 종류. site의 `build-info.json` 기록과 다르면 종료 코드 3 |
| `--site` | 종류별 기본 | `build/web/site` 또는 `build/web-dev/site` |
| `--browser` | `chrome` | `chrome`·`msedge` 또는 실행 파일 경로 |
| `--headless` / `--headed` | headless | 헤드리스는 소프트웨어 렌더러(SwiftShader)로 WebGL 2를 쓴다 |
| `--port` | 0 | 서버 포트. 0이면 빈 포트 자동 선택 |
| `--run-root` | `artifacts/runs` | 실행 폴더 위치(Git 제외) |
| `--shot-inverted 0\|1` | (지정 안 함) | "Shoot by default" 설정 값을 결과 `config`에 기록하고 페이지에 알린다(아래 6절) |

## 4. 종료 코드

종료 코드는 **실행 전체**가 어떻게 끝났는지만 말한다. 에피소드 상태(`timeout`·`error`·`invalid` 등)는 에피소드 파일의 `run.status`·`run.reason`과 `summary.json`으로 본다.

| 코드 | 의미 | 에피소드 파일 |
| --- | --- | --- |
| 0 | 요청한 에피소드를 모두 시도했고 정리도 깨끗함. 개별 에피소드의 `timeout`·`error`도 0 | 모두 있음 |
| 2 | 인자·설정 오류, 미지원 옵션(시드), 브라우저를 찾지 못함. 실행 시작 전 | 없음 |
| 3 | 산출물 없음·`build-info.json` 없음·`taisei.wasm` 해시 불일치·빌드 종류 불일치(`--stage`/`--spell`인데 릴리스 빌드 포함). 실행 시작 전 | 없음 |
| 4 | 서버·브라우저·페이지를 띄우지 못하거나 1번 에피소드가 `playing`/브리지 준비에 이르지 못함 | 있을 수 있음(오류 기록) |
| 5 | 2번 이후 에피소드를 시작하지 못했거나 실행기 내부 오류로 남은 에피소드를 시도하지 못함 | 일부 |
| 6 | 에피소드는 끝났지만 **정리가 깨끗하다고 확인되지 않음**. `run.json`의 `cleanup.status`로 구분한다: `leak`(브라우저 프로세스·임시 프로필·서버 포트·입력 해제가 남은 것이 확인됨), `unknown`(프로세스 조회 실패, 입력 해제 확인 실패, 정리 단계 예외처럼 확인 못 함 — 정리 검증 성공이 아님) | 모두 있음 |
| 130 | 사용자 중단(Ctrl+C, Windows는 Ctrl+Break·SIGTERM도 같은 경로). 중단된 에피소드는 `aborted/user_abort` | 일부 |

2·3·4의 실패도 `run.json`(`exit_code`, `error`)에 남긴다. 6은 v0.1 표에 없던 코드로 이번 v1에서 추가했다.

## 5. 빌드 종류와 출처 기록

- `scripts/build-web.ps1 -Flavor release|developer`. 기본은 `release`이며 `build/web/**`와 그 출처 기록 규칙은 바꾸지 않았다.
- `developer`는 `build/web-dev/{install,install-provenance.json,site}`에 같은 구조로 만들고 meson에 `-Ddeveloper=true`를 더한다. 치트·디버그 인자(`--play`·`--sid`·`--diff`·`--shotmode`·`--skip-to-bookmark`, `src/cli.c`의 `#ifdef DEBUG`)와 테스트 스테이지가 켜진다.
- `build-info.json`의 `build`에 `flavor`, `mesonOptions`, `rulesPreserved`를 기록한다. `developer`의 `rulesPreserved`는 `"unverified"`(검증 전까지 원본 규칙 보존 미확정), `release`는 `"original"`(개발자 기능이 없는 기본 빌드)다. `flavor`가 없는 기록(이 변경 이전의 릴리스 빌드)은 `release`로 읽는다.
- `-PackageOnly`는 `install-provenance.json`의 종류가 요청한 `-Flavor`와 다르면 거부한다.
- 개발자 빌드 결과는 원래 규칙의 클리어 증거로 쓰지 않는다. 사용 자체는 `invalid`가 아니며(세션 4 합의) 치트가 관측될 때만 평가가 `invalid / rule_violation`으로 바꾼다.

## 6. 페이지와의 신호 (Q4 답): `window.taiseiAI` 호스트 API

실행기와 수동 UI가 같은 경로를 쓴다. 이름은 세션 5 제안(`enable·suspend·resume·disable·state·onEvent`)을 그대로 쓴다. 소유자는 세션 5(셸)·세션 2(브리지)이고, 실행기는 아래 시점에 아래 방식으로만 부른다.

### 6.1 실행기가 하는 일 (시점 순서)

1. 페이지 이동 전에 **초기화 스크립트**로 `window.taiseiAIRun`(6.3)과 이벤트 수집기를 심는다.
2. `window.taiseiShell.state`가 `ready`가 되면 `#start`를 **실제 마우스 입력(CDP)**으로 누른다. `playing`이 되면 시작 완료. `error`·`unsupported`·`exited`면 시작 실패.
3. (`bridge` 모드) `window.taiseiAI`가 나타날 때까지 기다려 `onEvent(cb)`를 구독하고, `await taiseiAI.ready`(있으면)로 호스트의 초기화(브리지 연결·빌드 정보)를 기다린다. 끝내 없으면 시작 실패(종료 코드 4).
4. **시작 신호**: `--policy`가 `none`이 아니면 `await taiseiAI.loadPolicy(policy, params)`(실패 → `error / policy_error`), 이어서 `await taiseiAI.enable(options)`. 호스트의 `enable()`은 반환 코드를 주므로 `'ok'`·`'noop'`이 아니면 시작하지 못한 것이다(`no_policy`·`policy_error` → `error / policy_error`, 그 밖의 `not_playing`·`unavailable`·`bridge_error` → `error / runner_error`). `options = { episode_index, scenario, policy:{name,version,params}, limits:{max_frames} }`는 호스트가 무시해도 된다.
5. 0.25초마다 `state()`와 쌓인 이벤트를 읽는다. 아래 중 하나가 되면 감시를 끝낸다(위에서부터 먼저 맞는 것).
   - `episode_end` 이벤트(선택, 호스트가 보내면 우선) → `run.status`는 이벤트의 `status`(`completed`·`error`·`aborted`, 없으면 `completed`), `run.reason`은 이벤트의 `reason`
   - `state()`의 소유권 전환으로 파생(브리지 계약 `CONTRACT.md` 4절의 사유 코드). 이벤트가 없어도 브리지만으로 끝을 안다.

     | `owner_state` / `owner_reason` | `run.status` / `run.reason` |
     | --- | --- |
     | `ai_suspended` / `stage_end` | `completed` / `stage_end` |
     | `ai_suspended` / `game_over` | `completed` / `game_over` |
     | `ai_suspended` / `restart` | `aborted` / `user_abort` (실행기가 요청한 재시작이 아니므로) |
     | `ai_suspended` / `not_playing` | `error` / `runner_error` (`enable`이 거부됨: 진행 중인 스테이지가 아님) |
     | `manual` / `user_input` | `aborted` / `user_abort` |
     | `manual` / `policy_error` | `error` / `policy_error` |
     | `manual` / `observation_invalid` | `error` / `observation_invalid` (최종 판정은 평가) |
     | `manual` / `bridge_error` | `error` / `runner_error` |

     `pause`·`focus_lost` 등 그 밖의 정지는 끝으로 보지 않고 이벤트·`owner_transitions`로만 남긴다(계획 외 정지 판정은 평가).
   - 논리 프레임 한도: `state()`의 프레임(`frame`·`last_frame`·`lastFrame`)이 `enable` 시점 프레임보다 `max_frames` 이상 늘면 `completed / frame_limit`. 현재 호스트 API(PR #42)에는 한도 옵션이 없어 **실행기가 폴링으로 감지**한다(한도 120프레임 전부터 0.04초 간격으로 좁혀 폴링하지만 몇 프레임 넘길 수 있고, 그때 `run.detail`에 `runner_detected`를 적는다). 호스트가 한도를 정확히 집행하게 되면(`enable` 옵션으로 `limits.max_frames`를 이미 넘기고 있다) 그 값을 따른다. 스펠·스테이지 종료로 끝나는 실험에서는 프레임 한도가 안전장치일 뿐이다. 한도의 기준 프레임은 `enable` **직전** 샘플이며(직후 첫 샘플을 기준으로 하면 그 사이 프레임이 빠진다), `runner.frame_progress`에 `pre_enable_frame`(enable 직전에 새로 읽은 샘플)·`first_sample_frame`·`end_frame`(감시 구간에서 마지막으로 본 프레임)·`cleanup_frame`(정리 단계에서 본 프레임, 한도 판단과 구분)·`elapsed_frames`·`exceeded_by`·`limit_detected_by`(`runner`|`host`)를 남긴다. 폴링으로 감지한 한도는 정확 N프레임 비교에 쓰지 않는다.
   - 벽시계 한도 → `timeout / wall_timeout`
   - 셸이 `error`·`exited`·`unsupported`가 되거나 브라우저 연결이 끊김 → `error / runner_error`
6. **정지 신호**: `await taiseiAI.disable('host_request')`. 직후 `state()`로 입력 해제를 확인한다(6.2).
7. 로그·증거를 모으고 페이지 → 브라우저 → 서버 순으로 닫는다.

`suspend`·`resume`은 실행기가 쓰지 않는다. 일시정지·포커스 상실로 생긴 `ai_suspend`는 이벤트로 기록만 하고, 계획에 없는 정지의 판정(`unexpected_pause`)은 평가(세션 4)가 한다. 자동 재활성화는 하지 않는다(#21 v0.2).

### 6.2 페이지가 지켜야 할 것 (세션 2·5에 요청)

- `state()`는 가볍게 JSON 직렬화되는 객체를 돌려준다. 실행기가 읽는 필드:

  | 필드 | 뜻 |
  | --- | --- |
  | `ready` | 브리지 준비 여부(없으면 준비됨으로 본다) |
  | `owner_state`·`owner_reason`(어댑터) 또는 `mode`·`reason`(호스트 API, PR #42) | 이름 문자열 또는 정수 코드(브리지 계약 4절의 0=`manual`·1=`ai_active`·2=`ai_suspended`, 사유 코드 0~13). 두 이름과 두 형태 모두 이해한다 |
  | `frame`·`last_frame`·`lastFrame`, `episode_id`·`episodeId`, `gameover` | 논리 프레임, 에피소드 번호, 종료 유형(`WIN`·`DEFEAT` 등) |
  | `input` | (선택) `{ hold, pending_edges, queued_actions }` 정수 |
  | `settings.shot_inverted` | (선택) 실제 적용된 "Shoot by default" 값 |

  입력 해제 판정: `disable('host_request')` 뒤 `input`이 있으면 모두 0이고 `owner_state`가 `manual`/`ai_suspended`일 때만 해제됨(`basis: counters`). `input`이 없으면 `owner_state == manual`이면 해제됨으로 본다(브리지 계약 4.1: `disable`은 대기 중인 액션 슬롯·엣지를 모두 버린다. 증거 수준이 낮으므로 `basis: owner_state`로 구분해 기록). 둘 다 알 수 없으면 `unknown`이며, `released: false`일 때만 종료 코드 6이다.
- `onEvent` 이벤트는 `{ type, frame?, episode_id?, ... }`. 소유권 전환(`ai_enable`·`ai_suspend`·`ai_resume`·`ai_disable`, 또는 호스트의 `{type:'transition', mode|state|to, reason}`)은 `owner_transitions`에도 반영한다. 호스트의 전환 이벤트 필드는 세션 5가 확정해 주기 바란다(현재 `mode`·`state`·`to` 중 하나로 가정). 실행기가 의미를 두는 것은 둘뿐이다.
  - `episode_end`(선택): `{ status?, reason, frame }` — 호스트가 종료를 직접 알릴 때. 없어도 위 파생 규칙으로 끝을 안다.
  - `artifact`: `{ name, encoding: "utf8"|"base64", data }` — 큰 데이터(trace·리플레이)를 조각으로 보낸다. 같은 `name`의 조각은 이어 붙여 저장한다. `trace.jsonl`은 `episodes/NNNN.trace.jsonl`(`evidence.trace`), `replay.tsr`은 `episodes/NNNN.replay.tsr`(`evidence.replay`)로 평가 스키마의 기본 경로에 두고, 그 밖의 이름은 `episodes/NNNN/<name>`이다. 이름은 `[A-Za-z0-9._-]{1,64}`.
  나머지 이벤트(`ai_enable`·`ai_suspend`·`hit`·`bomb` 등)는 그대로 `episodes/NNNN.events.jsonl`에 쌓는다.
- 실행기는 이벤트를 해석해 지표를 만들지 않는다. 지표는 평가가 그 파일에서 만든다.

### 6.3 실행기가 페이지에 넘기는 설정: `window.taiseiAIRun`

페이지 스크립트가 실행되기 전에 심으므로 URL 쿼리 파싱이 필요 없다.

```json
{
  "run_id": "20261029T143255Z-b57c25", "experiment_id": "spell-s1-easy", "episode_index": 1, "episodes_total": 3,
  "mode": "bridge",
  "scenario": { "kind": "spell", "id": "…", "difficulty": "Easy", "shotmode": "youmuA" },
  "policy": { "name": "avoid-v1", "version": "", "params": {} },
  "limits": { "max_frames": 3600, "wall_timeout_s": 180 },
  "game_args": ["--sid", "…", "--diff", "Easy", "--shotmode", "youmuA"],
  "shot_inverted": null
}
```

- `game_args`: 개발자 빌드에서 게임 `main`에 줄 인자. **셸이 `callMain(game_args)`로 넘겨야** 효과가 있다(현재 셸은 인자 없이 호출). 세션 5와 조정한다.
- `shot_inverted`: "Shoot by default" 기본값이 웹 빌드에서 바뀔 예정이다(총괄 세션 예고). 지정하면 값을 `config.shot_inverted`에 기록하고 페이지에 알린다. 지정하지 않으면 `null`로 기록하며, 프로필이 매번 새것이라 저장된 이전 설정은 섞이지 않는다. 적용은 셸·브리지가 한다.

## 7. 결과 저장 구조

```text
artifacts/runs/<run_id>/            # run_id = YYYYMMDDTHHMMSSZ-<6hex>, artifacts/는 Git 제외
├── run.json          # 실행 매니페스트(아래). `args`=해석된 실행 인자, `config`=평가 스키마의 config 모양(에피소드와 같은 블록). 시작 때 쓰고 끝에 다시 쓴다(중간에 죽어도 finished:false 기록이 남음)
├── summary.json      # 요청·시도 수, 상태별·사유별 개수, 종료 코드. 지표는 없다
├── build-info.json   # 사용한 site의 출처 기록 사본
├── episodes/
│   ├── 0001.json             # 에피소드 파일(세션 4 스키마). 실패·중단도 지우지 않는다
│   ├── 0001.events.jsonl     # 페이지가 보낸 원시 이벤트(평가 입력)
│   └── 0001/                 # artifact 이벤트로 받은 파일, 실패·smoke의 last-screen.png
└── logs/
    ├── runner.log  server.log  browser-console.log  game.log   # 에피소드는 [epNNNN] 접두/구분선으로 구분
```

### 7.1 블록 분담 (세션 4 합의)

| 블록 | 쓰는 주체 | 내용 |
| --- | --- | --- |
| `schema`, `run_id`, `experiment_id`, `episode_index`, 시각 | 실행기 | `schema`는 세션 4 확정값 `taisei-ai-episode/1`(PR #41), run.json은 `taisei-ai-run/1` |
| `code` | 실행기 | `main_commit`, `dirty`(합산: 어느 출처든 변경이 있으면 `true`, 확인 못 한 출처가 있으면 `null`, 모두 비어 있어야 `false`), `dirty_entries`(실행기 checkout), `dirty_sources`(`runner_checkout`·`build_repository`·`build_taisei_worktree`·`packaging_repository`·`web_shell`별 목록 또는 `null`=확인 불가. `git status` 실패는 clean이 아니라 `null`),  `taisei_commit`, **`build_flavor`**(`release`·`developer`), `meson_options`, `rules_preserved`(`original`=기본 빌드, `unverified`=개발자 빌드), `build_info_sha256`, `wasm_sha256`, `build_repository_commit`, `build_started_at` |
| `config` | 실행기 | `scenario`(`kind`·`id`·`difficulty`·`character`·`shot`, smoke는 `kind: "menu"`), `policy`(`params_sha256` 포함), `seed`(`control: "random"`, `required: false`, `requested`·`actual`·`source`는 `null`: 시드를 지정하지 않고 게임이 `makeseed()`를 쓴다), `limits`, `mode`, `shot_inverted`·`shot_inverted_source`, `game_args` |
| `run` | 실행기가 `error`·`timeout`·`aborted`·`completed` + 원시 사실 | `status`, `reason`, `evaluable`, `detail`, `elapsed_s`, `error_message`. 평가가 상태를 바꾸면 원래 값을 **`run.status_by_runner`**에 남긴다. 실행기는 이 필드를 쓰지 않는다 |
| `owner_transitions`, `final`, `episode_id` | 실행기 | 소유권 전환 목록(`frame`·`wall_ms`·`state`·`reason`), 끝에 읽은 `{gameover, last_frame}`, 브리지 에피소드 번호 |
| `result`, `events`, `metrics` | 평가(세션 4) | 실행기는 `result: null`로 두고, 이벤트 원본은 `evidence.events` 파일로 넘긴다 |
| `runner` | 실행기 | `startup_s`, `running_s`, `bridge_present`, `shell_states`, `first_state`, `last_state`, `console_errors`, `input_release`, `cleanup`, `cleanup_status`, `cleanup_errors`, `evidence_errors`, `frame_progress` 등 실행 사실 |
| `evidence` | 실행기 | `events`, `artifacts`, `game_log`, `console_log`, `screenshot`, `log` 경로(run 폴더 기준 상대) |

- `run.status`: `completed`(요청한 한도·종료까지 정상 진행) · `timeout`(벽시계 한도) · `error`(브라우저·서버·셸·브리지 오류) · `aborted`(사용자 중단). `invalid`·`unsupported`는 평가가 정한다.
- `run.evaluable`은 `bridge` 모드에서 `completed`일 때만 `true`다(평가가 뒤집을 수 있음).
- **`summary.json`은 상태별·사유별 개수만** 센다. 성공률·분포 같은 지표는 평가가 `evaluation.json`으로 따로 쓴다.
- 코드/출처가 `dirty`인 결과는 재현 증거로 쓰지 않는다. `build_info_sha256`와 `wasm_sha256`으로 같은 산출물인지 확인한다.

## 8. 프로세스·입력 정리 규칙

- 실행기는 **자기가 띄운 것만** 정리한다. 서버는 PID와 포트, 브라우저는 실행마다 새로 만든 임시 프로필(`taisei-ai-profile-*`) 경로로 식별한다. 기존 게임·서버·브라우저 창은 건드리지 않는다.
- 에피소드마다 새 브라우저·새 임시 프로필을 쓴다. IndexedDB 상태(설정·진행·리소스 캐시)가 에피소드 사이에 섞이지 않는다. 대가로 에피소드마다 게임 로드 시간이 든다.
- 종료 순서: 입력 해제 요청과 확인 → 증거 수집 → 페이지 종료 → 브라우저 종료(`Browser.close`, 안 되면 프로필 경로로 찾은 프로세스만 강제 종료) → 서버 종료 → 포트가 닫혔는지 확인. 예외·Ctrl+C에도 같은 순서를 `finally`에서 실행한다.
- 정리 단계(입력 해제 확인 → 증거 수집 → 브라우저 종료 → 서버 종료)는 **각각 예외를 격리**한다. 앞 단계가 예외·중단으로 끝나도 브라우저와 서버 종료는 실행되고, 실패는 `runner.cleanup_errors`(정리 단계)·`runner.evidence_errors`(증거 수집·저장)에 남는다. artifact 저장 실패가 실행을 멈추게 하지 않는다.
- 외부 명령으로 프로세스를 조회하다 **실패(비정상 종료 코드·시간 초과)하면 "일치하는 프로세스 없음"으로 보지 않고** `remaining: null`(확인 불가, `unknown`)로 남긴다. 직접 띄운 브라우저·서버 프로세스의 생존은 조회 결과와 무관하게 `Popen.poll()`로 독립 확인해, 살아 있으면 `leak`이다.
- 로그 기록(`runner.log`)과 최종 기록 파일(`summary.json`·`run.json`) 쓰기 실패는 정리 흐름을 멈추지 않는다(로그는 best effort, 드라이버·서버 종료·최종 기록을 각각 격리). `summary.json` 기록이 실패하면 `run.json`을 쓰기 전에 종료 코드를 5로 확정해 프로세스 반환 코드와 `run.json`의 `exit_code`가 같다. `run.json` 자체를 쓰지 못하면 기록으로 남길 수 없으므로 표준 오류와 반환 코드(5)로만 알린다. 어느 쪽이든 정상(0)으로 보고하지 않는다.
- 정리 판정은 에피소드마다 `runner.cleanup_status`(`clean`·`unknown`·`leak`), 실행 전체는 `run.json`의 `cleanup.status`다. `unknown`(프로세스 목록을 못 읽음, 브리지가 있었는데 입력 해제를 확인하지 못함, 정리 단계 예외)은 누수 확정이 아니지만 정리 검증 성공도 아니므로 `cleanup.ok`가 거짓이고 종료 코드 6이다. 브리지가 없는 smoke(`no_bridge`)는 해제할 입력이 없어 `clean`이다.

## 9. 브라우저 제어 방식을 CDP 직접 연결로 정한 이유

| | CDP 직접(채택) | Playwright |
| --- | --- | --- |
| 설치 | 없음(표준 라이브러리 + 설치된 Chrome/Edge) | `pip install playwright` + 드라이버 |
| 재현 | 새 checkout에서 바로 실행 | 버전 고정·설치 단계 필요 |
| 프로세스 소유 | 직접 `Popen`해 PID와 프로필 경로를 안다 → 누수 검사가 정확 | 브라우저 PID 접근이 제한적 |
| 위험 | WebSocket 클라이언트를 직접 유지(약 150줄, 프레임 단위 테스트 있음) | 라이브러리 성숙도 높음 |

실행기는 페이지 안에서 정책이 도는 구조라 CDP 사용량이 작다(이동, 평가, 클릭, 스크린샷). 프레임마다 왕복이 필요해지면 Playwright 전환을 별도 이슈로 다시 따진다.

## 10. 다른 세션에 요청

- **세션 2(#21, 브리지)**: 6.2의 `state()` 필드. 입력 누수의 증거가 `owner_state`뿐이므로, 가능하면 `status` 블록에 입력 상태 카운터(`input.hold` 등)를 노출해 주기. 시드 지정이 생기면 `state().seed_control`을 알려 주면 `--seed`를 활성화한다. 브리지는 스테이지를 시작하지 않으므로(CONTRACT 7절) 시작은 실행기(게임 인자)·셸이 맡는다.
- **세션 5(#24, 셸)**: `window.taiseiAI` 노출, `window.taiseiAIRun.game_args`를 `callMain`에 전달, `build-info.json`의 `build.flavor`가 `developer`면 "원본 규칙 보존 미확정" 경고 표시.
- **세션 4(#23, 평가)**: 에피소드 파일의 `schema` 문자열 확정, `run.reason`에 실행기가 쓰는 `smoke_duration`(평가 제외용)과 `wall_timeout`·`runner_error`·`user_abort` 허용, `evidence.events`(JSONL)를 입력으로 사용.
- **세션 3(#22, 정책)**: 정책 이름(`--policy`)으로 정책을 불러오는 방식과 `window.taiseiAIRun.policy.params` 사용.

## 11. gitlink 갱신과 ai/** 패키징 (AI 단계에서는 세션 1만)

1. 최신 `origin/main`의 `game/taisei` gitlink와 fork(`kthss01/taisei`) `master`의 머지 커밋을 확인한다. 다른 작업(프롤로그 건너뛰기·자동 발사·한국어·캐릭터 이미지)이 머지한 fork 변경을 되돌리지 않는다.
2. 갱신 대상은 세션 2의 브리지 fork PR 머지 커밋을 포함한 최신 fork `master` 커밋이다.
3. gitlink 갱신 PR에 웹 재빌드 회귀(릴리스·개발자 빌드, `scripts/check-web-assets.py`, 실행기 smoke)를 함께 보고한다.
4. `build-web.ps1`은 `ai/bridge/taisei-ai-bridge.mjs`를 `site/game/ai/bridge/`로, `ai/policies/**`(`.js`·`.mjs`·`.json`)를 `site/game/ai/policies/**`로 패키징한다(세션 5 호스트 API가 이 위치를 가정한다. 셸 파일 `web/game/ai-host.js`는 `web/game/` 복사에 포함되어 `webShellSha256`에 들어간다). `build-info.json`의 `packaging`에 `aiPackaged`, `aiDirtyEntries`(`ai/`의 미커밋 변경), `aiSha256`(패키징한 파일별 해시)을 남기고, 패키징된 ai 파일의 dirty는 `code.dirty` 합산(`dirty_sources.packaged_ai_files`)에 들어간다. `ai/bridge/`가 없는 브랜치에서는 건너뛰고 `aiPackaged: false`로 남긴다.
