# AI 평가: 결과 스키마 v1, 측정 정의, 평가 도구

담당 이슈: [#23](https://github.com/kthss01/mini-danmaku-ai-claude/issues/23) · 부모: [#19](https://github.com/kthss01/mini-danmaku-ai-claude/issues/19)
구현: `evaluation/`(도구·스키마·평가 세트) · 검증: `tests/ai-evaluation/`

이 문서는 실행 결과(원시 로그)를 어떻게 읽어 에피소드마다 판정하고, 정책과 기준선을 어떻게 비교하는지를 정한다. 설계 이력은 #23 댓글 v0·v0.1·v0.2와 Q6 답변에 있다.

## 0. 상태와 가정

| 항목 | 상태 |
| --- | --- |
| 브리지 계약 v1 (`docs/ai/CONTRACT.md`, `feat/ai-bridge` fd63e57) | 맞춤. 이 문서의 이벤트·카운터·`cheat_flags`·`overflow`·`act_*`·사유 코드는 그 문서를 따른다 |
| 실행 계약 v1 (#20) | **미확정**. #20 v0.1 5절(run 폴더 구조)을 **가정**한다. v1이 올라오면 `schemas/run.schema.json`·`episode.schema.json`을 맞춘다 |
| trace 파일 | **가정**. 호스트(실행기·정책 번들)가 논리 프레임마다 한 줄을 쓴다. 형식은 `schemas/trace.schema.json` |
| 실제 게임 결과 | **없음**. 검증은 가정한 형식으로 만든 합성 fixture뿐이다. fixture 결과는 정책 성능이나 게임 동작을 증명하지 않는다 |

가정 목록은 매 리포트의 마지막 절에도 찍힌다.

## 1. 파이프라인

```text
artifacts/runs/<run_id>/                 (실행기가 쓴다. 평가 도구는 읽기만 한다)
  run.json                               실행 매니페스트 (taisei-ai-run/1)
  episodes/NNNN.json                     에피소드 원시 기록 (taisei-ai-episode/1)
  episodes/NNNN.trace.jsonl              프레임별 trace (taisei-ai-trace/1)
        │
        ▼  python evaluation/evaluate.py evaluate <run_dir>
<run_id>/evaluation/                     (평가 도구가 쓴다)
  evaluation.json                        판정·지표·그룹 요약·실패 설명 (taisei-ai-evaluation/1)
  episodes.csv   groups.csv              표 형식 요약
  report.md                              사람이 읽는 리포트
        │
        ▼  python evaluation/evaluate.py compare <run>... --out <dir>
comparison.json / .csv / .md             기준선 대 정책 (taisei-ai-comparison/1)
```

- 평가 도구는 실행기의 `episodes/*.json`·`summary.json`을 **고치지 않는다**(테스트가 해시로 확인한다). 판정은 `evaluation.json`에 따로 쓴다.
- 같은 입력이면 `generated_at`을 뺀 결과가 같다(재생성 가능).
- 표준 라이브러리만 쓴다(Python 3.12). 스키마 검증은 `evaluation/taisei_eval/schema_lite.py`가 맡는다(저장소 스키마가 쓰는 키워드만 지원하는 작은 검증기).

## 2. 책임 분담

| 블록 | 쓰는 주체 | 비고 |
| --- | --- | --- |
| `run.json`, 에피소드의 `run_id`·`code`·`config`·시각·증거 경로 | 실행기(#20) | 가정 A1 |
| 에피소드의 `run.status`: `completed`·`timeout`·`aborted`·`error`와 원시 사실(종료 코드, 경과 시간, 오류 메시지) | 실행기 | |
| `owner_transitions` | 호스트(브리지 `onEvent`) | 일시정지 구간은 관측 프레임이 없어 여기서 읽는다 |
| trace | 호스트 | 가정 A2 |
| `invalid`·`unsupported`·`missing` 판정, `result`·`events`·`metrics`·`quality`, 요약 | **평가 도구** | |

평가 도구가 실행기의 `completed`를 바꾸면 `run.status_by_runner`에 원래 값과 `overridden: true`를 남긴다. 바꾸지 않아도 항상 `status_by_runner`를 채운다.

## 3. 스키마 v1

JSON Schema 파일은 `evaluation/schemas/`에 있다.

| 파일 | `schema` 값 | 쓰는 주체 | 내용 |
| --- | --- | --- | --- |
| `run.schema.json` | `taisei-ai-run/1` | 실행기 | 요청 에피소드 수, 공통 `code`·`config`, 종료 코드 |
| `episode.schema.json` | `taisei-ai-episode/1` | 실행기·호스트 | `code`, `config`, 실행기 `run`, `owner_transitions`, `final`, `evidence` |
| `trace.schema.json` | `taisei-ai-trace/1` | 호스트 | 프레임당 한 줄 |
| `evaluation.schema.json` | `taisei-ai-evaluation/1` | 평가 도구 | 에피소드 판정, 그룹 요약, 실패 설명 |
| `comparison.schema.json` | `taisei-ai-comparison/1` | 평가 도구 | 기준선 대 정책 비교 |

### 3.1 `config`에서 평가가 읽는 것

| 필드 | 뜻 |
| --- | --- |
| `scenario` | `kind`(`spell`·`stage`), `id`, `difficulty`, `character`, `shot` |
| `policy` | `name`(`idle`·`simple-move`·`avoid-v1` …), `version`, `params_sha256` |
| `seed.control` | `random`(지정 안 함) · `set`(`set_seed` 주입) · `replay` · `unsupported`(요구했으나 쓸 수 없음) |
| `seed.required` | true인데 실제 출처(`source`)가 `set`이 아니면 평가는 `unsupported / seed_unsupported`로 판정한다 |
| `seed.requested` / `actual` / `source` | 요청 값, `obs.meta.seed_hi:seed_lo`(16진수), `seed_source` 0/1/2 → `random`/`set`/`replay` |
| `limits` | `max_frames`(논리 프레임), `wall_timeout_s`(벽시계) |
| `shot_inverted` | `CONFIG_SHOT_INVERTED`(Shoot by default) 값 0/1/null. 웹 빌드 기본 1(Z를 누르지 않으면 쏘고, 누르는 동안 멈춘다). 저장된 브라우저 설정에 0이 남을 수 있어 **기록해야 한다**. `shot_inverted_source`는 `web_default`·`saved_setting`·`forced`·`unknown` |
| `pre_hit_window_frames` | 피격 전 구간 길이(기본 120) |

- 브리지 액션의 `hold.SHOT`에는 반전이 적용되지 않는다(CONTRACT 6.1). 반전은 사람의 물리 키에만 영향을 준다. 그래도 `shot_inverted`가 다른 실행은 서로 비교하지 않는다(그룹 조건에 들어 있다).
- `code.build_flavor`(`release`·`developer`)와 `rules_preserved`(`original`·`unverified`)를 기록한다. 개발자 빌드 사용은 `invalid`가 아니지만 요약 caveat에 "원본 규칙 보존 미검증"이 붙는다.

### 3.2 `v0.2` 대비 바뀐 것

| 항목 | v0.2 | v1 |
| --- | --- | --- |
| 상태 | `completed`·`timeout`·`aborted`·`error`·`unsupported`·`invalid` | 위에 `missing` 추가: 요청했는데 파일이 없거나 읽지 못한 에피소드. 분모에서 빠지지 않는다 |
| `seed.control` | `unsupported`·`replay`·`set` | `random`·`set`·`replay`·`unsupported`. 브리지 v1이 시드 주입을 지원하므로 "지정 안 함"은 `random`이다 |
| 파일 분리 | `summary.json`은 실행기, 지표는 `evaluation.json` | 그대로 확정 |
| `run.reason_code` | 제안 | 브리지 `owner_reason` 문자열 원본. 상태를 바꾼 전환이 없으면 null |
| 입력 적용 지연 | `act.target_frame − obs.frame`이 아니라 실제 적용 프레임 − 근거 관측 프레임 | trace의 `frame − act_last_obs_frame` (`act_applied`가 오른 프레임만) |
| `quality.action_sync` | `stale`·`dup`·`missing` | `rejected`·`applied` 추가. 에피소드 끝 값 |
| 요약 분모 | 두 가지 | 그대로. `*_all`·`*_evaluable` 두 쌍을 항상 같이 낸다 |
| `starts` (그룹) | 없음 | 실행 순서 점검용 시작 시각 목록 |

## 4. 측정 정의

모든 프레임은 논리 프레임(`obs.meta.frame`, 60 FPS 기준)이다. 시간(초) = 프레임 / 60.

| 지표 | 정의 | 출처 |
| --- | --- | --- |
| `frames_total` | 마지막 관측 프레임 − 첫 관측 프레임 + 1 | trace |
| `frames_survived` | 첫 **사망(counted)** 프레임 − 첫 프레임. 사망이 없으면 `frames_total`. `seconds_survived` = /60 | trace, `death` 이벤트 |
| 피격 `hits` | `phase` 0→1 전이 수 (`hit` 이벤트) | trace |
| 사망 `deaths` | `phase` 1→2 전이 수 중 Extra 스펠 예외가 아닌 것(`counted: true`). 예외는 `uncounted_deaths` | trace |
| 데스봄 `deathbombs` | `phase` 1→4 전이 수 | trace |
| 봄 | `bombs_policy`(phase 0·3→4)와 `bombs_deathbomb`(1→4)를 나눠 센다 | trace |
| 컨티뉴 | 마지막 관측의 `continues`. 1 이상이면 스테이지 클리어가 아니다 | trace |
| 판단 지연 `decision_ms` | 정책이 관측을 받은 뒤 액션을 돌려줄 때까지 ms. `n`, p50, p95, max, `over_policy_budget`(> 4 ms), `over_frame_budget`(> 16.67 ms). 백분위수는 nearest-rank | trace `decision_ms` |
| 입력 적용 지연 | 액션이 적용된 프레임 − 그 액션의 근거 관측 프레임. 설계상 1, `missing`이면 커진다. p50·max | trace `act_applied`·`act_last_obs_frame` |
| 실행 속도 `sim_fps` | 연속한 두 관측 사이 벽시계 차이로 계산한 논리 프레임 / 초. **owner_state가 1(`ai_active`)이 아닌 구간과 프레임이 이어지지 않는 구간은 뺀다**(일시정지·정지 구간). `below_60_ratio` = 60프레임 창 중 fps < 57(60의 95%)인 창의 비율 | trace `wall_ms` |
| `shot_hold_ratio` | 적용된 hold에 SHOT 비트가 있는 프레임 비율. 정책이 실제로 쏘는지 점검 | trace `hold_applied` |
| `quality.overflow_frames` | `overflow ≠ 0`인 관측 수. `overflow_kinds`는 비트 이름(`bullets`·`lasers`·`laser_segs`·`enemies`) | trace |
| `quality.observation_complete` | `overflow_frames == 0`이고 프레임 누락·중복이 없음 | trace |
| `quality.conservative_frames` | `act_mode == conservative`인 프레임 수(정책의 보수 동작 구간) | trace |
| `quality.action_sync` | 마지막 관측의 `act_stale`·`act_dup`·`act_missing`·`act_rejected`·`act_applied` | trace |

- 판단 지연은 정책 계산만 잰다. 브라우저 왕복 지연은 `sim_fps`와 입력 적용 지연으로 따로 본다. 4 ms는 #22의 실측 전 목표값이며 실측 후 다시 정한다.
- 값을 얻을 수 없으면 `null`로 두고 `metrics.unavailable`에 이름을 적는다(숨기지 않는다).

### 4.1 이벤트

이벤트는 `phase` 전이로만 만든다. `lives`·`bombs` 증감으로 추정하지 않는다.

| 전이 | 이벤트 |
| --- | --- |
| 0 → 1 | `hit` |
| 1 → 2 | `death` (`counted: false`는 같은 프레임에 `ev_death_uncounted`가 오른 경우) |
| 1 → 4 | `deathbomb` |
| 0·3 → 4 | `bomb` (`source: policy`) |
| 0 → 2 (hit_pending을 관측하지 못함) | `hit`+`death`, 둘 다 `inferred: true` |
| `owner_transitions`의 `ai_suspended`·`ai_active` | `suspend`(+사유)·`resume` |

`ev_hit`·`ev_death`·`ev_death_uncounted`·`ev_bomb` 카운터는 이벤트 수와 교차 확인만 한다. 하나라도 다르면 `invalid / observation_invalid`이다.

## 5. 에피소드 판정

### 5.1 상태와 사유

| `run.status` | 의미 | 정책 성능에 반영 |
| --- | --- | --- |
| `completed` | 실행이 정상으로 끝까지 돌았다. 정책이 죽어도 `completed`다 | 예 (`evaluable: true`) |
| `timeout`·`aborted`·`error` | 실행기가 판정한 실행 문제 | 아니오 |
| `unsupported` | 요구한 조건(시드 지정)을 쓸 수 없었다 | 아니오 |
| `invalid` | 규칙 위반·계획 외 정지·관측 불일치 | 아니오 |
| `missing` | 요청한 에피소드의 파일이 없거나 읽지 못했다 | 아니오 (분모에는 남는다) |

`run.reason`: `frame_limit` · `spell_end` · `stage_end` · `game_over` · `wall_timeout` · `user_abort` · `runner_error` · `policy_error` · `observation_invalid` · `rule_violation` · `unexpected_pause` · `seed_unsupported` · `episode_file_missing` · `episode_file_unreadable` · `unknown`. 모든 `notes`에 판정 근거가 문장으로 남는다.

### 5.2 `completed`로 기록된 에피소드를 바꾸는 규칙 (우선순위 순)

| 순위 | 조건 | 결과 |
| --- | --- | --- |
| 1 | `cheat_flags`의 비트 0(`iddqd`)·1(리플레이 치트 표시)·2(스킵 모드), `cheat_events > 0`, `phase == normal`인데 `vulnerable == 0` | `invalid / rule_violation` (비트 3 개발자 빌드 표시는 위반이 아니다) |
| 2 | 에피소드·trace 스키마 위반, 카운터 불일치, trace 프레임 누락·중복, `episode_id`가 여러 개, trace 없음·빈 trace, 브리지 `observation_invalid` 전환 | `invalid / observation_invalid` |
| 3 | 전환 `pause`·`focus_lost` → `ai_suspended` | `invalid / unexpected_pause` |
| 4 | `seed.required`인데 `seed.source`가 `set`(또는 `replay` 설정에서의 `replay`)이 아님 | `unsupported / seed_unsupported` |
| 5 | 전환 `policy_error`, `policy_deadline`이면서 `ai_suspended`, `bridge_error` | `error / policy_error` · `error / runner_error` |
| 6 | 전환 `user_input`, 정상 종료 없이 `restart`, 종료 유형 `ABORT`·`RESTART` | `aborted / user_abort` |

여러 규칙에 걸리면 가장 높은 순위가 상태가 되고 나머지는 `notes`에 "추가 사유"로 남는다. `dialog`·`stage_end`·`game_over`·`not_playing`·`host_request`(종료 후) 전환은 상태를 바꾸지 않는다.

아무 규칙에도 걸리지 않으면 종료 사유는 이 순서로 정한다: `gameover`가 `WIN`/`SCORESCREEN` → `spell_end`/`stage_end`; 관측 프레임 수 ≥ `max_frames` → `frame_limit`; `DEFEAT` → `game_over`. 어느 쪽도 아니면 trace가 중간에 끊긴 것이므로 `invalid / observation_invalid`("정상 종료 조건 없음")이다.

실행기가 `timeout`·`aborted`·`error`로 기록한 에피소드는 그대로 두고, 규칙 위반 표시가 보이면 `notes`에만 적는다. 그런 에피소드도 `events`·`metrics`는 부분 trace로 계산하지만 `result`는 `null`이고 그룹 지표(생존 프레임 등)에는 들어가지 않는다.

### 5.3 `result` (평가 가능한 에피소드만)

| 필드 | 정의 |
| --- | --- |
| `survived` | counted 사망이 0회 (프레임 한도·스펠 종료까지 포함) |
| `first_death_frame` | 첫 counted 사망 프레임 |
| `pattern_captured` (`kind: spell`) | `spell_end`로 끝났고 피격 0, 봄(정책·데스봄) 0, 사망 0. 프레임 한도 도달은 캡처가 아니다 |
| `stage_cleared` (`kind: stage`) | `stage_end`로 끝났고 사망 0, 컨티뉴 0 |
| `gameover_type` | 마지막으로 관측된 `gameover` 이름 |

## 6. 요약과 성공의 의미

그룹 = 정책(이름·버전) × 조건(시나리오·`build_flavor`·`shot_inverted`·`max_frames`·`wall_timeout_s`).

| 지표 | 분모 | 용도 |
| --- | --- | --- |
| `survive_all` · `capture_all`(`clear_all`) | **시작한 모든 에피소드**(timeout·error·aborted·unsupported·invalid·missing 포함) | 실행 안정성을 포함한 실제 성능 |
| `survive_evaluable` · `capture_evaluable`(`clear_evaluable`) | `evaluable == true`인 에피소드 | 정책 자체의 성능 |
| `survive_evaluable_complete_obs` / `_incomplete_obs` | 평가 가능 중 관측 완전/불완전 | 불완전 관측 구간의 성공은 안전 판단 증거로 쓰지 않는다 |

- 모든 비율은 `k`, `n`, `rate`, Wilson 95% 구간 `wilson95`를 같이 낸다. 분모가 0이면 `rate`와 구간이 `null`이다.
- 상태별·사유별 개수(`counts.by_status`, `by_reason`)를 같은 그룹에 둔다. 어떤 에피소드도 파일에서 지우지 않는다.
- Wilson 구간은 에피소드가 서로 독립이라는 가정에서만 맞는다. 같은 브라우저 세션을 이어 쓰는 등 독립이 깨질 수 있는 조건은 caveat로 적는다.
- **단일 성공**은 에피소드 1회의 목표 달성이다. **반복 성공**은 같은 조건 N회 중 k회(위 비율)다. 단일 성공을 반복 성공이나 일반적 클리어 근거로 쓰지 않는다.
- 판단 지연은 그룹 전체 샘플을 합쳐(pooled) 백분위수를 낸다.

### 6.1 시드와 반복 구분

| `seed_design` | 조건 | `comparison_class` |
| --- | --- | --- |
| `uncontrolled` | 모든 에피소드 `seed.control == random` | `exploratory` |
| `single_seed` | 시드 1개, 에피소드 1개 | `controlled` |
| `fixed_seed_repeat` | 시드 1개를 2회 이상 | `controlled` |
| `multi_seed` | 시드 2개 이상 (시드마다 반복 횟수는 `seed_info`) | `controlled` |
| `replay` / `mixed` | 리플레이 / 섞임 | `controlled` / `exploratory` |

- `exploratory`는 정책 우열을 확정하는 근거가 아니다. 리포트가 그렇게 표시한다.
- **재현성**: 브리지 8.2절대로 상태 해시·리플레이 desync 검사를 통과하기 전까지 모든 그룹의 `reproducibility`는 `not_verified`로 **고정**한다. 같은 시드 반복의 이벤트 일치는 `same_seed_agreement`(관측된 일치 여부)로만 보인다.
- 소표본(시작 30개 미만)은 caveat로 표시한다.

### 6.2 지원하지 않거나 검증하지 못한 항목 (`support`)

`reproducibility: not_verified` · `frame_step: unsupported`(브리지 v1) · `browser_roundtrip_latency: not_measured` · `seed_control: supported|not_measured`(관측된 에피소드 기준) · `rules_preservation_developer_build: not_verified`(개발자 빌드가 있을 때). 그룹의 `unsupported_items`에는 지표 수집이 안 된 항목(`decision_ms`, `input_lag_frames`, `sim_fps`)이 들어간다.

## 7. 기준선 대 정책 비교

`compare`는 같은 `condition_key`의 그룹끼리만 비교한다.

- 시나리오는 같은데 빌드·`shot_inverted`·한도가 다르면 비교하지 않고 경고를 남긴다.
- 기본 기준선은 `idle`(정지), `simple-move`(주기적 좌우 이동). `--baselines`로 바꾼다. 기준선이 없으면 그 사실을 적는다.
- 정책 대 기준선마다 생존율 차(전체·평가 가능 분모)와 Wilson 구간 분리 여부(`higher_intervals_separate`·`lower_intervals_separate`·`intervals_overlap`)를 낸다. p값은 내지 않는다.
- 실행 순서: 정책별 시작 시각을 모아 같은 정책이 연속한 최대 길이를 센다. 번갈아 실행하지 않았으면(최대 연속 > 1) 시간대·발열·브라우저 상태 변화가 한 정책에 몰릴 수 있다고 경고한다.

### 7.1 초기 고정 평가 세트 제안 (`evaluation/configs/eval-set-v0.json`)

| 항목 | 제안 |
| --- | --- |
| 대상(dev) | 스펠 연습 Stage 1 스펠 1개, Easy. 스펠 `id`는 개발자 빌드의 스펠 목록을 확인한 뒤 ai-runner와 확정한다(지금은 null) |
| 기체 | 1조합 고정(`marisa`/`marisaA`) |
| 보류(holdout) | Stage 1의 다른 스펠 1개, 다른 기체 1조합(`youmu`/`youmuA`). 튜닝에는 쓰지 않고 최종 보고에서만 따로 표시한다 |
| 정책 | `idle`, `simple-move`, 회피 정책(`avoid-v1`) |
| 한도 | `max_frames` 3600(스펠 제한 시간에 맞춤), `wall_timeout_s` = 예상 시간 × 2 + 60초 |
| 탐색 비교 | 시드 미지정, 정책마다 30회, 정책을 번갈아 실행 (총 90) → `exploratory` |
| 시드 비교 | 시드 20개(`seed_base + i`) × 1회 × 정책 3 = 60, 그리고 같은 시드 5회 × 정책 3 = 15 (총 75) → `controlled`이지만 재현성은 `not_verified` |
| 순서 | `idle → simple-move → avoid-v1 → idle …` |

`python evaluation/evaluate.py plan --mode seeded|uncontrolled [--holdout] [--out plan.json]`이 이 세트를 실행 순서가 정해진 목록으로 펼친다. 실행기가 이 목록을 그대로 따르면 순서와 시드가 결과에 남는다. 이 개수는 제안이며, 실제 실행 시간·부하를 보고 ai-runner·ai-integration과 조정한다.

## 8. 충돌 직전 구간 (실패 설명)

평가 가능한 에피소드의 `hit` 이벤트마다(에피소드당 최대 3개) 피격 전 `pre_hit_window_frames` 프레임(기본 120 = 2초)을 추려 `failures[]`에 둔다.

- `window`: 시작·끝 프레임, 프레임 수
- `actions`: 적용된 hold를 연속 구간으로 묶은 목록(예: `LEFT+SHOT × 12`)
- `position`: 구간 시작·끝 위치
- `nearest_bullet`: 구간 안에서 플레이어(판정은 점)와 탄 가장자리 사이 거리가 가장 짧은 순간. trace의 `near`(가까운 탄 최대 8개의 `[id, x, y, 반지름]`)가 있어야 한다
- `evidence`: trace·리플레이·로그 경로
- `tags`: 단서일 뿐 원인 증명이 아니다 — `observation_incomplete`(구간에 overflow), `action_sync_degraded`(`missing`·`stale`·`dup` 증가), `decision_over_frame_budget`·`decision_over_policy_budget`, `conservative_mode`, `no_movement_input`(마지막 30프레임에 방향 입력 없음), `near_boundary`(경계 24 이내), 아니면 `unclassified`

정책 실패(`completed` + `survived: false`)와 실행 문제(`timeout`·`error`·`unsupported`·`invalid`·`missing`)는 상태로 구분된다. 실행 문제 에피소드는 실패 설명을 만들지 않는다.

## 9. 사용법

```bash
python evaluation/evaluate.py evaluate artifacts/runs/<run_id>
python evaluation/evaluate.py compare artifacts/runs/<idle> artifacts/runs/<simple> artifacts/runs/<policy> --out artifacts/compare/<name>
python evaluation/evaluate.py plan --mode seeded --out plan.json
python evaluation/evaluate.py validate evaluation <run>/evaluation/evaluation.json
python -m unittest discover -s tests/ai-evaluation -v
```

종료 코드: 0 정상 · 2 입력·인자 오류 · 3 출력이 스키마를 만족하지 않음. 평가 대상 에피소드의 실패·누락은 종료 코드에 영향을 주지 않는다(리포트에 남는다).

fixture 생성: `python tests/ai-evaluation/fixture_builder.py --out <폴더>` (정책 3종, 같은 조건, 번갈아 시작한 합성 run 3개).

## 10. 검증 현황과 미결정

- 검증됨(fixture): 스키마 통과/거부, 상태 판정 규칙 전부, 분모 두 가지와 누락 보존, 이벤트·카운터 교차 확인, 지표 값, 시드 설계 분류, 비교 조건 분리, 실행 순서 경고, 평가 세트 펼치기, 입력 파일 불변, 결과 재생성.
- **검증 못 함**: 실제 게임·브리지·실행기에서 나온 trace. trace 형식은 가정(A2)이고, 실제 필드 이름·단위가 다르면 `trace.schema.json`과 `judge.py`를 맞춘다.
- 실행기(#20)와 정할 것: ① 에피소드 파일·trace 위치와 이름, ② trace를 누가 쓰는지, ③ `restart` 전환을 정상 경계로 볼 조건(지금은 정상 종료 없이 `restart`면 중단), ④ `final.gameover`를 쓰는지, ⑤ 평가 세트의 스펠 `id`와 반복 수.
- 정책(#22)과 정할 것: `act_mode: conservative`를 trace에 싣는지, 4 ms 목표값.
- 4 ms 예산, 느린 창 기준(57 fps), 120프레임 구간은 실측 후 다시 정한다.
