# AI 브라우저 통합 QA

담당: 세션 5 · 이슈 [#24](https://github.com/kthss01/mini-danmaku-ai-claude/issues/24) · 부모 [#19](https://github.com/kthss01/mini-danmaku-ai-claude/issues/19)
설정과 호스트 API: [docs/AI_SETUP.md](../AI_SETUP.md). 웹 쪽 QA는 [docs/web/QA.md](../web/QA.md)가 별도로 있다.

## 증거 구분 (공통 검증 원칙)

| 구분 | 뜻 | 클리어 증거 |
| --- | --- | --- |
| `미실행` | 아직 확인하지 않았다 | 아니오 |
| `mock` | 가짜 어댑터·가짜 Module로 확인했다. UI·전환 로직·호스트 코드의 동작만 보여 준다 | 아니오 |
| `fixture` | 세션 2의 실제 어댑터 코드를 가짜 Module(`tests/ai-bridge/mock-module.mjs`)에 연결해 확인했다. 어댑터와 호스트의 접합만 보여 준다 | 아니오 |
| `실제` | 실제 게임(wasm)에서 확인했다 | 항목 조건을 충족할 때만 |

이 문서의 상태는 확인한 만큼만 `mock`·`fixture`·`실제`로 적는다. 사람이 직접 확인하지 못한 항목은 성공 처리하지 않는다.

## 항목

항목 번호는 #24 통합 설계 v0(2026-10-23)의 AI-01~AI-50 초안을 그대로 쓰고, 세부 항목을 더했다.

### AI-0x 환경·빌드

| ID | 항목 | 절차 | 기대 | 상태 |
| --- | --- | --- | --- | --- |
| AI-01 | 새 checkout에서 빌드·서빙·실험·결과 조회 재현 | 새 clone → setup → 개발자 빌드 → 서빙 → 실행기로 에피소드 1회 → 결과 조회 | 문서대로 재현된다 | 미실행(실행기·브리지 대기) |
| AI-02 | 개발자 빌드 경고 | `build-info.json`의 `build.flavor`를 `developer`로 바꾼 사본에서 `?ai=mock` | "원본 규칙 보존이 확정되지 않았습니다" 경고, `rulesPreserved: unverified` | mock |
| AI-03 | 릴리스에 AI UI가 없다 | 파라미터 없이 `game/index.html`을 연다(브리지 없는 빌드) | AI 패널이 없고 `taiseiAI.state().available === false`, 셸 오류 없음 | mock(브리지 없는 기존 산출물 사본) |
| AI-04 | 브리지 없음 안내 | `?ai=1`(브리지 없는 빌드) | "AI 사용 불가 — 이 게임 빌드에는 AI 브리지가 없습니다" | mock(브리지 없는 기존 산출물 사본) |
| AI-05 | 어댑터 호환 | `tests/ai-integration/bridge-compat.test.mjs` | 호스트가 어댑터 v1의 메서드·사유 코드와 맞는다 | fixture(PR #39 `fd63e57`의 어댑터, 5건 통과). 어댑터가 main에 들어오면 이 경로로 상시 실행 |

### AI-1x 모드 전환·입력 해제

| ID | 항목 | 절차 | 기대 | 상태 |
| --- | --- | --- | --- | --- |
| AI-10 | 모드 표시·버튼, 자동 재활성화 없음 | AI 시작 → 정지 → 재개 → 수동으로. 일시정지 해제·포커스 복귀 뒤 상태를 본다 | 배지·버튼이 상태를 따른다. 일시정지·포커스 상실 뒤 `ai_suspended`가 유지된다 | mock(내장 브라우저, DOM 클릭 이벤트). 실제 미확인 |
| AI-11 | 정지·실패·포커스 상실·일시정지에서 입력 해제 | 각 사유로 정지시킨 뒤 대기 슬롯·엣지가 비었는지, 적용 입력이 물리 키로 돌아갔는지 | 슬롯 폐기, 다음 프레임부터 물리 키 | mock·fixture(슬롯 폐기). 실제 관측(`inputflags`, `meta` 카운터)은 미확인 |
| AI-12 | AI 중 사용자 키 | `ai_active`에서 게임 키 입력 | 즉시 `manual`(`user_input`), 입력을 섞지 않음 | mock(DOM 키 이벤트로 흉내). 실제는 브리지(C) 구현 대기 |
| AI-13 | 호스트 API 계약 | `taiseiAI.ready` → `loadPolicy` → `enable` → `state` → `disable` | 반환 코드·`state()` 필드가 `docs/AI_SETUP.md`와 같다 | mock·fixture(단위 27건) |
| AI-14 | 오류 표시 | 정책 예외·잘못된 액션·정책 초기화 실패 | `manual`(`policy_error`), 오류 문구, 로그 `[AI]` 줄 | mock |
| AI-15 | 공격 입력 정의 | 수동(`shot_inverted` 켬/끔)과 AI에서 공격이 어떻게 나가는지 | 수동: 반전은 물리 키에만. AI: `hold.SHOT`은 항상 공격 | 정의만 문서화(CONTRACT 6.1). 실제 미확인 |
| AI-16 | 게임 모듈 abort·종료 때 해제 | 게임이 abort/exit 되는 경우 | 셸이 `disable('bridge_error' / 'host_request')`를 먼저 부른다 | 코드 경로만 구현. 미실행 |

### AI-2x 한 패턴 폐루프

| ID | 항목 | 절차 | 기대 | 상태 |
| --- | --- | --- | --- | --- |
| AI-20 | 한 패턴 폐루프 | 스펠 연습 Stage 1의 스펠 1개, 캐릭터·샷 1조합. 관측 → 정책 → 입력 → 결과 저장 | 에피소드 결과가 평가 스키마로 저장된다 | 미실행(브리지 C·정책·실행기 대기) |
| AI-21 | 프레임 지연 | `stale` / `dup` / `missing` 카운터, 판단 시간 p50/p95 | 동기 콜백에서 `missing = 0`, 판단 p95가 프레임 예산 안 | 호스트의 판단 시간 통계는 mock. 실제 미확인 |
| AI-22 | 에피소드 경계 | 재시작·다음 스테이지 | `episode_id`가 올라가고 정책이 `reset`된다 | mock(호스트 로직). 실제 미확인 |

### AI-3x 리플레이

| ID | 항목 | 절차 | 기대 | 상태 |
| --- | --- | --- | --- | --- |
| AI-30 | AI 입력이 리플레이에 기록 → 저장 → 새로고침 → 재생 일치 | AI 에피소드를 저장하고 새로고침 뒤 원본 재생기로 본다 | 재생 결과가 일치한다 | 미실행(계약상 `player_event` 경로로 기록, 확인 필요) |
| AI-31 | `--verify-replay` | 저장한 리플레이를 헤드리스로 검증 | 비동기화 없음 | 미실행 |
| AI-32 | 결정성 | 같은 시드·액션 열 N회 | 상태 해시 일치 | 미실행(`reproducibility: not_verified` 유지) |

### AI-4x 수동 플레이 회귀

| ID | 항목 | 절차 | 기대 | 상태 |
| --- | --- | --- | --- | --- |
| AI-40 | 키보드 수동 플레이·오디오·저장 | [docs/web/QA.md](../web/QA.md)의 핵심 항목을 AI 파일이 들어간 셸에서 재실행 | 웹 QA와 같은 결과 | 일부만: AI 셸 파일을 덮어쓴 사본에서 DOM 키 이벤트(Z 간격 입력)로 인트로가 진행됨. 오디오·저장·스테이지 조작·창 전환은 미실행 |
| AI-41 | `?ai=0`·파라미터 없음일 때 셸이 이전과 같다 | 셸 오류 목록, HUD, 키 전달 | 오류 없음, HUD 동일 | 오류 없음·HUD 표시는 확인(mock/기존 산출물 사본). 실제 키 입력 회귀는 AI-40에 포함 |

### AI-5x 규칙 보존

| ID | 항목 | 절차 | 기대 | 상태 |
| --- | --- | --- | --- | --- |
| AI-50 | 규칙 보존(무적·속도 변경 없음) | 관측의 `cheat_flags`, `cheat_events`, `p_vulnerable`, `p_speed_*`를 에피소드마다 기록 | 이상 없음, `rules_preserved` 기록 | 미실행(브리지 C·평가 대기) |
| AI-51 | 개발자 빌드 결과 표기 | 개발자 빌드 결과를 클리어 증거로 쓰지 않는다 | 결과 JSON에 `build_flavor`가 남고 증거 요약에서 제외 | 셸 경고만 구현(AI-02). 결과 쪽은 세션 1·4 |

## 실행 기록

### 2026-10-29 mock 검증 (셸 AI 연결 PR)

- 기준: main `a32fa43`(PR #38 머지) 위의 `test/ai-integration`.
- 호스트 단위·호환 테스트: `node --test tests/ai-integration/*.test.mjs` → main 트리에서 22 통과 + 5 건너뜀(어댑터 없음), PR #39 `fd63e57`의 어댑터·fixture를 둔 스크래치 트리에서 27 통과.
- 화면 확인: main `acf9b62`(PR #34 이전) 기반의 기존 산출물 `mini-danmaku-ai-claude-qa2/build/web/site`를 자기 출력 폴더(`mini-danmaku-ai-claude-ai5-out/site`)에 복사하고, 이번 브랜치의 `web/game/{index.html,shell.js,shell.css,shell-config.js,ai-host.js}`와 `tests/ai-integration/mock-adapter.js`(`game/ai-mock-adapter.js`)만 덮어썼다. 원본 폴더는 바꾸지 않았다. 게임 wasm은 AI 브리지가 없는 기존 빌드(Taisei `a95dafae`)다.
- 내장 브라우저(Claude 데스크톱 앱, 포트 8153)에서 확인(**DOM 이벤트 기반**이며 실제 키 입력이 아니다):
  - `?ai=mock`: 배지 `수동` → `AI 시작` 클릭 → `AI 동작 중`(적용 입력 18프레임, `missing` 1) → `정지`(슬롯 폐기) → `재개` → 게임 키 이벤트 → `수동`(`user_input`) → `Esc` → `AI 정지`(`pause`) → 재개 시도는 `not_playing`으로 유지 → 일시정지 해제 후에도 자동 재개 없음 → `blur` → `AI 정지`(`focus_lost`) → `focus` 뒤에도 자동 재개 없음 → `수동으로` → `수동`.
  - `build.flavor = developer`로 바꾼 사본: 개발자 빌드 경고와 mock 경고가 함께 표시되고 `rulesPreserved: unverified`. 확인 뒤 `build-info.json`을 원래대로 되돌렸다.
  - `?ai=1`: `AI 사용 불가 — 이 게임 빌드에는 AI 브리지가 없습니다`, 버튼 없음, `enable()` → `unavailable`, 셸 오류 없음.
  - 파라미터 없음: AI 패널 숨김, `available: false`, 셸 오류 없음, HUD 표시.
  - `?ai=mock`에서 Z 키 이벤트(약 200 ms 간격)로 게임 인트로가 진행되어 키가 게임에 계속 전달됨.
- 아직 하지 않은 것: 실제 브리지·정책·gitlink 연동, 실제 게임 입력, 리플레이, 오디오·저장 회귀, 실제 포커스 전환(자동화로 만들 수 없음), 전체 수동 플레이 QA.
