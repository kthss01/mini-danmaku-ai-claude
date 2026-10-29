# AI 브리지 계약 v1 (관측·액션·종료·시드·상태 전이)

담당 이슈: [#21](https://github.com/kthss01/mini-danmaku-ai-claude/issues/21) · 부모: [#19](https://github.com/kthss01/mini-danmaku-ai-claude/issues/19)
기준 소스: fork `kthss01/taisei` `master` `1d4b468d` (게임 프레임 루프·입력·판정 코드는 이전 기준 `f59212b7`과 같다)
구현·제약·측정 비용: [BRIDGE.md](BRIDGE.md) · 이 문서는 **다른 세션이 의존하는 계약**만 담는다.

이 문서가 정하는 것은 다음 다섯 가지다.

1. 관측 `taisei.ai.obs/1` — 한 논리 프레임 끝의 게임 상태
2. 액션 `taisei.ai.act/1` — 다음 프레임에 적용하는 입력
3. 프레임 시점·메모리 수명 — 관측과 액션이 어느 지점에서 맞물리는지
4. 소유권 상태 `owner_state`와 전환 사유 코드
5. 시드·재시작·종료·미지원 항목

설계 이력은 #21 댓글 v0(6374918326)·v0.1(6374930234)·v0.2(6375383663)에 있다. 이 문서가 그 위에서 남은 결정을 정하고 일부를 정정한다(11절).

## 0. 용어

| 용어 | 뜻 |
| --- | --- |
| 논리 프레임 | `stage_logic_frame` 1회. 60 FPS 기준 게임 시간 1틱. `global.frames`로 센다 |
| 틱 F | `global.frames == F`인 상태로 실행되는 논리 프레임 |
| 관측 `obs` | 틱 F의 모든 태스크가 끝나고 `global.frames++` 직전에 캡처한 상태. `obs.frame = F` |
| 액션 `act` | `obs.frame = F`를 보고 정한 입력. 틱 F+1의 `process_input`에서 적용된다. `target_frame = F + 1` |
| 에피소드 | `_stage_enter` 1회부터 `stage_finish`·재시작까지. `episode_id`로 구분한다 |
| 호스트 | 브리지를 부르는 쪽. 웹 셸(세션 5), 실행기가 연 페이지의 스크립트(세션 1), 정책 번들(세션 3)이 모두 해당한다 |

좌표계: viewport 480 × 560, 원점은 왼쪽 위, +x는 오른쪽, +y는 아래쪽이다. 위치는 `cmplx`의 (실수부=x, 허수부=y)다. 단위는 viewport 단위(픽셀과 같은 척도)이고 시간은 논리 프레임이다. 모든 실수는 `float32`로 내보낸다(원본은 `double`). 경계 판정을 정확히 재현해야 하는 정책은 이 정밀도 한계(약 3×10⁻⁵)를 여유에 넣는다.

## 1. 프레임 시점 (가장 중요)

```
틱 F  : stage_logic_frame
          cosched_run_tasks            ← stage_comain(process_input → boss → enemies → projectiles → items → lasers)
                                          그 뒤 스테이지 스크립트·적·보스 태스크가 같은 틱에서 이어서 실행된다
          update_all_sfx
          stage_replay_sync
          ★ 관측 캡처 (obs.frame = F)       ← 호스트 콜백(동기 모드)이 여기서 액션을 등록할 수 있다
          global.frames++                   ← F+1
틱 F+1: process_input                       ← ★ 액션 적용 (target_frame = F+1)
          이어서 같은 틱에서 탄 이동·충돌
```

- **캡처 지점은 `stage_comain` 본문 끝이 아니라 `cosched_run_tasks` 직후다.** `stage_comain`은 가장 먼저 만들어진 태스크라서 같은 틱에서 가장 먼저 돈다. 그 뒤에 도는 패턴·적 태스크가 탄을 새로 만들거나 `pos`·`move`를 바꾼다. `stage_comain` 끝에서 캡처하면 이 변경이 빠져서 다음 틱 충돌 시점의 상태와 어긋난다. 원본 소스의 `cosched_run_tasks`(`coroutine/cosched.c`)가 태스크를 생성 순서대로 실행함을 근거로 했다. (이슈 요청 문구 "stage_comain 끝, frames++ 전"과 다른 점이며, 틱 끝 상태라는 의도는 같다.)
- 따라서 `obs`는 **틱 F+1에서 플레이어가 움직이고 탄이 이동·충돌하기 직전의 상태**다. 액션은 이 관측에서 정한다.
- **입력 지연은 항상 1프레임**이다(관측 틱 F → 적용 틱 F+1). 동기 콜백 모드에서는 같은 틱 안에 액션을 등록하므로 `missing`이 생기지 않는다.
- **레이저 구간만 한 틱 늦다.** `laser_segs[]`는 틱 F의 `process_lasers`가 만든 충돌 구간이다. 틱 F의 레이저 태스크가 그 뒤에 모양을 바꾸면(이동·충전) 틱 F+1의 실제 충돌 구간은 그 변경분만큼 다르다. 레이저는 `lasers[]`의 `width`·`active`와 함께 한 프레임 오차 여유를 둔다.
- 첫 관측: `_stage_enter` 뒤 첫 `cosched_run_tasks`는 `stage_comain`의 `begin`만 실행하고 `process_input`을 돌리지 않는다. 그래서 첫 관측은 `frame = 0`이고 그 액션은 `frame = 1`에 처음 적용된다. 그 전 틱은 입력이 없다(hold 0).
- 관측은 **논리 프레임마다** 낸다. 브라우저 콜백 1회에 논리 프레임이 여러 개 도는 경우(리플레이 스킵)에도 프레임마다다. 일시정지·메뉴 중에는 프레임이 진행하지 않으므로 관측도 없다(상태는 `status`로 읽는다, 6.3절).

## 2. 관측 `taisei.ai.obs/1`

브리지는 **관측 버퍼를 시작할 때 한 번 정적으로 할당**한다. 주소는 바뀌지 않지만 내용은 다음 캡처 전까지만 유효하다(수명, 3절). 형식은 SoA이고 필드 이름이 계약이다. 오프셋은 계약이 아니다. `taisei_ai_layout()`이 돌려주는 JSON으로 푼다(어댑터가 처리한다. 하드코딩하지 않는다).

### 2.1 스칼라 필드 (`i32` 블록 / `f32` 블록)

`i32` 블록은 `Int32`로, 비트필드는 부호 없는 값으로 해석한다. 정수 필드를 `f32` 뷰로 읽지 않는다.

**meta**

| 필드 | 형 | 의미 |
| --- | --- | --- |
| `schema_ver` | i32 | 이 문서의 관측 버전. 1 |
| `frame` | i32 | 틱 번호 F (`global.frames`) |
| `episode_id` | i32 | `_stage_enter`마다 1 증가. 1부터 |
| `stage_id` | i32 | `StageInfo.id` |
| `stage_type` | i32 | `StageType` 값(스토리/스펠 등, 원본 열거값 그대로) |
| `difficulty` | i32 | `global.diff` |
| `practice` | i32 | 연습 모드 여부(`global.is_practice_mode`) |
| `replay_mode` | i32 | 1이면 리플레이 재생 중. 이 프레임의 입력은 리플레이가 정하고 액션은 적용되지 않는다 |
| `skip_mode` | i32 | 1이면 리플레이 스킵 프레임(`stage_is_skip_mode`) |
| `gameover` | i32 | `global.gameover`(`NONE=0`/`WIN`/`DEFEAT`/`ABORT`/`RESTART`/`SCORESCREEN`/`TRANSITIONING`, 원본 열거값). 값은 `layout.enums.gameover` |
| `paused` | i32 | 캡처 시점에 항상 0. 정지 중 상태는 `status`(6.3절) |
| `dialog_active` | i32 | 대화 진행 중 |
| `seed_lo`, `seed_hi` | i32 | 이 에피소드의 `rng_seed`(64비트의 하위/상위 32비트) |
| `seed_source` | i32 | 0=무작위(`makeseed`), 1=주입, 2=리플레이 |
| `cheat_flags` | i32 | 비트 0=`iddqd` 켜짐, 1=리플레이 출력에 치트 플래그 설정됨, 2=스킵 모드(스킵은 `iddqd`를 강제로 켠다), 3=개발자(DEBUG) 빌드 |
| `cheat_events` | i32 | 에피소드 시작부터 `player_event`가 치트 키로 처리한 횟수(`iddqd`·`powerup`·`powerdown`). 0이 아니면 클리어 증거에서 제외한다 |
| `overflow` | i32 | 비트 0=탄, 1=레이저, 2=레이저 구간, 3=적이 잘렸다(5절) |
| `n_bullets`, `n_lasers`, `n_segs`, `n_enemies` | i32 | 이 관측에 실제로 담긴 개수 |
| `total_bullets`, `total_lasers`, `total_segs`, `total_enemies` | i32 | 잘리기 전 실제 개수 |
| `owner_state` | i32 | 0=`manual`, 1=`ai_active`, 2=`ai_suspended` (4절) |
| `owner_reason` | i32 | 마지막 전환 사유 코드 (4.2절) |
| `owner_events` | i32 | 소유권 전환 횟수(에피소드와 무관하게 누적) |
| `act_applied` | i32 | 에피소드 시작부터 적용된 액션 수 |
| `act_stale` | i32 | 이미 지난 `target_frame`이어서 버린 액션 수 |
| `act_dup` | i32 | 같은 `target_frame`의 두 번째 이후라서 버린 액션 수 |
| `act_missing` | i32 | `ai_active`인데 그 프레임에 액션이 없어서 직전 hold를 유지한 횟수 |
| `act_rejected` | i32 | 에피소드 불일치·비활성 등 그 밖의 사유로 거부한 액션 수 |
| `act_last_obs_frame` | i32 | 마지막으로 적용된 액션의 근거 관측 프레임(= `target_frame − 1`). 적용 틱 − 이 값 = 입력 적용 지연 |
| `hold_applied` | i32 | 이 틱에 실제로 적용된 hold 비트(`inputflags`와 같은 값) |

`act_*` 카운터는 `_stage_enter`에서 0으로 돌아간다. `owner_events`·`episode_id`는 돌아가지 않는다.

**player**

| 필드 | 형 | 의미 |
| --- | --- | --- |
| `p_alive` | i32 | `player_is_alive` |
| `p_vulnerable` | i32 | `player_is_vulnerable` (`iddqd`·무적·봄 중이면 0) |
| `p_phase` | i32 | 0=`normal`, 1=`hit_pending`, 2=`dead`, 3=`recovering`, 4=`bombing` (2.3절) |
| `p_inputflags` | i32 | 원본 `inputflags` 비트(UP=1, DOWN=2, LEFT=4, RIGHT=8, FOCUS=16, SHOT=32, SKIP=64) |
| `p_focus` | i32 | 저속 입력 중 |
| `p_lives`, `p_bombs` | i32 | 잔기, 봄 |
| `p_power` | i32 | 유효 파워(`player_get_effective_power`) |
| `p_power_stored` | i32 | 저장 파워 |
| `p_graze` | i32 | 그레이즈 수(`uint`는 `i32`로 자른다) |
| `p_deathtime`, `p_respawntime`, `p_recoverytime`, `p_bomb_endtime` | i32 | 원본 필드 그대로 |
| `p_bomb_active`, `p_powersurge` | i32 | `player_is_bomb_active`, `player_is_powersurge_active` |
| `p_ev_hit` | i32 | 에피소드 내 `player_death()`가 실제로 진행된 횟수 |
| `p_ev_death` | i32 | `player_realdeath()` 횟수(Extra 스펠 중 사망 포함) |
| `p_ev_death_uncounted` | i32 | 그중 Extra 스펠이라 잔기·통계에 반영되지 않은 횟수 |
| `p_ev_bomb` | i32 | 봄 사용 횟수(`stats_track_bomb_used`) |
| `p_continues_used` | i32 | `stats.total.continues_used` |
| `p_x`, `p_y` | f32 | 위치 (히트박스 중심) |
| `p_vx`, `p_vy` | f32 | 직전 틱의 이동량(`plr->velocity`) |
| `p_speed_normal`, `p_speed_focus` | f32 | 현재 캐릭터의 보통/저속 속도(`PLR_PROP_SPEED`). 마리사 봄 중 감속 같은 일시 변화는 반영하지 않는다 |
| `p_hit_radius` | f32 | 플레이어 판정 반지름. **항상 0** (판정은 점이다) |

**boss**

| 필드 | 형 | 의미 |
| --- | --- | --- |
| `b_present` | i32 | 보스 존재 |
| `b_attack_type` | i32 | `global.boss->current->type`(없으면 −1) |
| `b_hp`, `b_maxhp` | f32 | 현재 공격의 체력(없으면 0) |
| `b_x`, `b_y` | f32 | 보스 위치 |

### 2.2 배열 필드 (SoA)

각 그룹은 `n_*`개까지 유효하다. 배열 길이는 `layout.arrays.<이름>.max`다.

**`bullets[]`** — `type == PROJ_ENEMY`이고 `PFLAG_NOCOLLISION`이 없는 탄

| 필드 | 형 | 출처 / 의미 |
| --- | --- | --- |
| `id` | u32 | `spawn_id`. 프레임 사이에 같은 탄을 추적한다 |
| `x`, `y` | f32 | `pos` |
| `px`, `py` | f32 | `prevpos`. 충돌은 `prevpos → pos`로 보간한 이동 선분 기준이다(순간이동 탄은 같은 값) |
| `wx`, `wy` | f32 | `collision_size`의 두 성분. **축 전체 길이(지름)다.** 반지름은 `/2`다 |
| `angle` | f32 | 타원 회전각 = `angle + π/2` (원본 `calc_projectile_collision`의 값) |
| `vx`, `vy` | f32 | `move.velocity` — 다음 `move_update`에서 `pos`에 더해질 값 |
| `ax`, `ay` | f32 | `move.acceleration` |
| `ret_re`, `ret_im` | f32 | `move.retention`. `velocity ← acceleration + retention × velocity` (복소수 곱) |
| `attr_re`, `attr_im` | f32 | `move.attraction`. 둘 다 0이면 인력 없음 |
| `attr_x`, `attr_y` | f32 | `move.attraction_point` |
| `attr_exp` | f32 | `move.attraction_exponent` |
| `flags` | u32 | 비트 0=`PFLAG_NOMOVE`(1이면 `move_update`를 쓰지 않고 태스크가 위치를 직접 바꾼다), 1=`PFLAG_INDESTRUCTIBLE`, 2=`PFLAG_NOGRAZE` |
| `age` | i32 | `global.frames − birthtime` |

`move_update`의 식은 `src/move.c`를 그대로 따른다: `pos += velocity; velocity = acceleration + retention × velocity; (attraction ≠ 0이면) velocity += attraction × (attraction_point − pos)·|…|^(exp−1)`. **정확도 제약:** 패턴 태스크가 중간에 `move`·`pos`를 바꾸는 탄이 많다. 이 필드만으로 하는 예측은 다음 변경 시점까지만 정확하다. 관측은 매 프레임 갱신되므로 롤아웃은 매 프레임 새로 해야 한다.

**`lasers[]`** — 충돌 대상 레이저와 충전 중인 레이저 모두. 구간은 `seg_start`부터 `seg_count`개

| 필드 | 형 | 의미 |
| --- | --- | --- |
| `id` | u32 | `spawn_id` |
| `active` | u32 | `laser_is_active`(`collision_active`). 0이면 충돌하지 않는다 |
| `birth` | i32 | `birthtime` |
| `timespan`, `deathtime`, `speed`, `width` | f32 | 원본 필드 그대로. `width`는 목표 폭 |
| `seg_start`, `seg_count` | u32 | `laser_segs[]`의 범위 |

**`laser_segs[]`** — 틱 F의 `process_lasers`가 만든 구간(1절의 한 틱 오차 참조)

| 필드 | 형 | 의미 |
| --- | --- | --- |
| `ax`, `ay`, `bx`, `by` | f32 | 구간 끝점 |
| `ra`, `rb` | f32 | 끝점 반지름 = `max(width/2 − 4, 2)`. 반지름이 양 끝에서 다른 캡슐로 판정한다 |

**`enemies[]`**

| 필드 | 형 | 의미 |
| --- | --- | --- |
| `id` | u32 | `spawn_id` |
| `x`, `y` | f32 | `pos` |
| `hurt_radius` | f32 | `enemy_get_hurt_radius`(0이면 접촉 무해) |
| `hp` | f32 | 체력 |
| `flags` | u32 | 원본 `EnemyFlag` 비트 그대로 |

**미제공 (v1):** 아이템, 아군 탄, 그레이즈 판정 형상, 대화 내용, 화면 효과, 레이저의 "활성까지 남은 프레임"(원본에 필드가 없다. `birth`·`width`로 추정한다), 보스 이외의 체력 바 정보.

### 2.3 `p_phase` 정의 (판정 순서대로 첫 번째로 맞는 값)

| 값 | 이름 | 조건 | 비고 |
| --- | --- | --- | --- |
| 1 | `hit_pending` | 피격됐고 `frame < p_deathtime` | 데스봄 유예. 봄을 쓰면 취소된다. `deathtime = 피격 프레임 + 데스봄 창` |
| 2 | `dead` | `p_alive == 0` 또는 `frame < p_respawntime`이면서 사망 처리가 끝났다 | 위치가 화면 밖 |
| 4 | `bombing` | `p_bomb_active` | 무적 |
| 3 | `recovering` | `frame < p_recoverytime` | 무적 |
| 0 | `normal` | 위에 해당하지 않음 | `p_vulnerable == 1`(`iddqd` 제외) |

`iddqd`가 켜지면 `p_phase`는 위 규칙을 따르되 `p_vulnerable = 0`이고 `cheat_flags`에 표시된다. 평가는 `phase` 전이로 이벤트를 만든다: `0→1` hit, `1→2` death, `1→4` deathbomb, `0/3→4` bomb. 같은 이벤트의 정확한 횟수는 `p_ev_*` 카운터와 교차 확인한다.

## 3. 메모리 수명·뷰 재생성

- 버퍼는 정적이다. 주소는 바뀌지 않지만 내용은 **다음 캡처 전까지만** 유효하다. 보관하려면 복사한다.
- 동기 콜백 모드에서는 콜백이 돌아오는 순간까지만 유효하다고 본다(콜백 안에서만 읽는다).
- 빌드가 `ALLOW_MEMORY_GROWTH=1`이다. 힙이 늘어나면 이전 `ArrayBuffer`는 분리(detach)되어 그 위의 모든 `TypedArray` 뷰가 길이 0이 된다. **어댑터는 관측을 읽기 전에 매번 현재 `wasmMemory.buffer`가 바뀌었는지 확인하고, 바뀌었으면 모든 뷰를 다시 만든다.** 이 조건을 어기는 호스트 코드는 계약 위반이다.
- 레이아웃: `taisei_ai_layout()`이 JSON 문자열의 포인터를 돌려준다(`taisei_ai_layout_size()`가 바이트 수). 스키마 버전, 블록·배열 오프셋(버퍼 기준 바이트), 형, 최대 개수가 들어 있다. 어댑터는 이 JSON만 믿는다.

## 4. 소유권 상태 `owner_state`

| 값 | 이름 | 입력 원천 | 사용자 게임 키 |
| --- | --- | --- | --- |
| 0 | `manual` | 물리 키(원본 그대로) | 원본 그대로 |
| 1 | `ai_active` | 액션 | **받으면 즉시 `manual`로 전환** (Q3, 4.3절). 입력은 섞지 않는다 |
| 2 | `ai_suspended` | 물리 키(원본 그대로) | 원본 그대로. 상태는 바뀌지 않는다 |

`ai_suspended`는 "AI가 입력을 쥐고 있지 않다"는 뜻이다. 사람이 일시정지 메뉴나 점수 화면을 조작하는 키는 그대로 게임에 전달된다. **자동으로 `ai_active`로 돌아가지 않는다.** 일시정지가 풀리거나 포커스가 돌아와도 `ai_suspended`가 유지되고, 호스트가 `resume`을 불러야 한다(세션 5 UI 또는 세션 1 실행기).

### 4.1 전환

| 호출 | 전 → 후 | 조건·결과 |
| --- | --- | --- |
| `enable()` | `manual` → `ai_active` | 진행 중인 스테이지(메뉴·일시정지·종료 아님)이고 리플레이 재생이 아니어야 한다. 아니면 `ai_suspended`(사유 `not_playing`)가 되고 반환값이 그 사실을 알린다 |
| `resume()` | `ai_suspended` → `ai_active` | 위와 같은 조건. 안 되면 `ai_suspended` 유지, 반환값으로 사유를 알린다 |
| `suspend(reason)` | `ai_active` → `ai_suspended` | 호스트가 요청. 이미 `ai_suspended`면 첫 사유를 유지한다 |
| `disable(reason)` | 임의 → `manual` | 대기 중인 액션 슬롯·엣지를 모두 버린다 |
| (브리지 자동) | `ai_active` → `ai_suspended` | 일시정지 진입(`pause`), 게임오버/컨티뉴 메뉴(`game_over`), 스테이지 종료(`stage_end`), 재시작(`restart`), 새 에피소드 진입 시 아직 `ai_active`이면 `restart` |
| (브리지 자동) | `ai_active` → `manual` | `ai_active` 중 사용자 게임 키 입력(`user_input`), 브리지 내부 오류(`bridge_error`) |

`manual`에서는 `suspend`가 무시된다. 전환마다 `owner_events`가 오르고 `owner_reason`이 갱신되며, 호스트가 `Module.taiseiAIOnEvent(kind, state, reason)`을 정의했으면 같은 순간에 호출한다(`kind`: 0=전환).

### 4.2 전환 사유 코드 (UI 표시·`owner_state` 전환·평가 `run.reason_code`가 같은 문자열을 쓴다)

| 코드 | 문자열 | 누가 | 전환 | 평가 대응(세션 4 #23 Q6 표) |
| --- | --- | --- | --- | --- |
| 0 | `none` | — | — | — |
| 1 | `pause` | 브리지 | → `ai_suspended` | `invalid` / `unexpected_pause` (계획된 정지가 아니면) |
| 2 | `focus_lost` | 호스트 | → `ai_suspended` | `invalid` / `unexpected_pause` |
| 3 | `dialog` | 호스트 전용 | → `ai_suspended` | 영향 없음(예약. 브리지는 대화 중에도 자동 정지하지 않는다, 아래 참조) |
| 4 | `stage_end` | 브리지 | → `ai_suspended` | `completed` / `spell_end`·`stage_end` |
| 5 | `restart` | 브리지 | → `ai_suspended` | `aborted` / `user_abort` (호스트가 요청한 재시작이면 정상 경계) |
| 6 | `host_request` | 호스트 | → `ai_suspended` 또는 `manual` | 호스트가 기록한 사유를 따름 |
| 7 | `user_input` | 브리지 | → `manual` | `aborted` / `user_abort` |
| 8 | `policy_error` | 호스트 | → `manual` | `error` / `policy_error` |
| 9 | `policy_deadline` | 호스트 | → `ai_suspended` 또는 계속 | 계속이면 영향 없음, 정지면 `error` / `policy_error` |
| 10 | `observation_invalid` | 호스트 | → `manual` | `invalid` / `observation_invalid` |
| 11 | `bridge_error` | 브리지 | → `manual` | `error` / `runner_error` |
| 12 | `game_over` | 브리지 | → `ai_suspended` | `completed` / `game_over` (컨티뉴 화면. 컨티뉴를 쓰면 클리어로 인정하지 않는다) |
| 13 | `not_playing` | 브리지 | `enable`/`resume`이 진행 중인 스테이지가 아니라서 `ai_suspended` | 영향 없음 |

세션 4가 제안한 후보 11개를 그대로 받고 `game_over`·`not_playing`을 더했다(#23 Q6 답변에 대한 확정). 문자열은 `layout.enums.owner_reason`에도 들어 있다.

**`dialog`를 자동 정지에 쓰지 않는 이유.** 대화 중에도 플레이어는 움직이고 탄도 있다. 정지하면 AI가 서 있는 동안 피격되거나 대화를 넘기지 못해 오히려 해롭다. 대화를 넘기는 입력은 `hold.skip`(원본 `INFLAG_SKIP`, 대화 페이지 넘김)으로 한다. 호스트가 대화 구간을 따로 다루고 싶으면 `meta.dialog_active`를 보고 직접 `suspend('dialog')`한다.

### 4.3 `ai_active` 중 사용자 키 (Q3)

- `ai_active`에서 사용자가 **게임 키**(이동·저속·공격·봄·스페셜·스킵·치트 키)를 누르면(`TE_GAME_KEY_DOWN`) 브리지는 즉시 `manual`로 전환하고(사유 `user_input`) 그 키 이벤트는 **게임에 전달하지 않고 버린다**. 이후 이벤트는 원본 그대로 처리된다. 누르고 있는 키의 상태는 다음 `process_input`의 `player_fix_input`이 물리 키 상태에서 다시 만든다.
- 키를 뗀 이벤트(`TE_GAME_KEY_UP`)는 `ai_active` 동안 무시한다.
- 시스템 키는 그대로 동작한다: 일시정지(`TE_GAME_PAUSE`), 재시작(F2), 포기(F1), 창 관리. 일시정지·재시작·포기는 4.1절의 자동 전환을 일으킨다.
- 게임패드 아날로그 입력은 `ai_active` 동안 무시한다(축 값을 0으로 본다). 사용자 키 전환 판정에는 쓰지 않는다. 버튼은 `TE_GAME_KEY_*`로 들어오므로 키와 같다.
- 입력을 섞지 않는다. AI와 사람이 번갈아 쓰려면 호스트가 `disable`/`enable`을 호출한다.

## 5. 관측 초과 정책 (overflow)

- 최대 개수를 넘으면 **잘라낸다.** `meta.overflow` 비트와 `total_*`(잘리기 전 실제 개수)를 함께 준다.
- 최대 개수(초안): 탄 4096, 레이저 64, 레이저 구간 4096, 적 256. 전 스테이지 실측 최대값의 2배 이상이어야 한다는 원칙은 유지하며, 실측은 [BRIDGE.md](BRIDGE.md)에 기록한다. 최대 개수가 바뀌면 `layout.arrays.*.max`와 스키마 부 버전이 바뀐다.
- **잘림 순서:** 탄은 플레이어와의 거리가 가까운 순으로 남긴다(같은 거리 구간 안에서는 원본 리스트 순서). 레이저 구간은 레이저 단위로 남기며, 구간이 들어가지 못한 레이저는 `seg_count`를 잘린 개수로 줄이고 `lasers` 쪽에도 `overflow` 비트 2를 켠다. 적은 리스트 순서다.
- `overflow ≠ 0`인 관측은 **불완전 관측**이다. 정책(세션 3)은 보수 동작으로 바꾸고 안전 판단을 주장하지 않는다. 평가(세션 4)는 그 프레임을 `quality.overflow_frames`로 센다. 불완전 구간의 성공은 안전 판단 증거로 쓰지 않는다.

## 6. 액션 `taisei.ai.act/1`

### 6.1 액션 값

| 필드 | 형 | 의미 | 게임 경로 |
| --- | --- | --- | --- |
| `hold` | 비트 | UP=1, DOWN=2, LEFT=4, RIGHT=8, FOCUS=16, SHOT=32, SKIP=64 (원본 `inputflags`와 같은 비트). 누름을 유지하는 입력 | 입력 처리 안에서 물리 키 대신 사용 → `player_event(EV_INFLAGS)` |
| `edges` | 비트 | BOMB=1, SPECIAL=2. 이 프레임에 한 번만 누르는 입력 | `player_event(EV_PRESS, KEY_BOMB / KEY_SPECIAL)` |

- 반대 방향(UP+DOWN, LEFT+RIGHT)을 동시에 주면 원본 규칙대로 상쇄된다(`player_applymovement`). 정규화는 원본이 한다.
- 대각선도 속도 × 단위 벡터다. 속도 변경은 불가능하다.
- `SHOT` 반전 설정(`CONFIG_SHOT_INVERTED`)은 **물리 키에만** 적용되고 액션에는 적용되지 않는다. `hold.SHOT`은 항상 "공격 중"이다.
- `AUTO_SURGE` 설정이 켜져 있으면 원본의 `player_fix_input`이 만드는 `EV_PRESS KEY_SPECIAL`은 그대로 일어난다(게임 설정이지 AI 입력이 아니다).
- **허용하지 않는 것:** `KEY_IDDQD`·`KEY_POWERUP`·`KEY_POWERDOWN` 같은 치트 키, 게임 속도 변경, 프레임 스킵, 퀵세이브/퀵로드는 액션으로 받지 않는다.

### 6.2 제출 (`submit`)와 처리

```
submit(episode_id, target_frame, hold, edges) → status
```

- `target_frame`은 반드시 **마지막 관측 프레임 + 1**이다. 한 번에 한 개만 대기한다(슬롯 1개).
- 상태 코드: 0=`accepted`, 1=`stale`(`target_frame`이 이미 지났다), 2=`dup`(같은 `target_frame`이 이미 있다), 3=`wrong_episode`, 4=`not_active`(`ai_active`가 아니다), 5=`future`(`target_frame`이 마지막 관측 프레임 + 1보다 크다), 6=`no_stage`(진행 중인 스테이지가 없다).
- `stale`·`dup`은 카운터를 올리고 버린다. 나머지 거부는 `act_rejected`를 올린다.
- 틱 F+1의 `process_input`에서:
  1. 슬롯의 `target_frame == F+1`이면 적용하고 슬롯을 비운다 (`act_applied`++, `act_last_obs_frame = F`).
  2. 슬롯이 비었으면 직전 `hold`를 유지하고 엣지는 반복하지 않으며 `act_missing`++.
  3. 슬롯의 `target_frame < F+1`이면 `act_stale`++로 버리고 2와 같이 처리한다.
- 입력 해제 보장: `ai_active`를 벗어나는 모든 전환은 슬롯과 대기 엣지를 즉시 버린다. 이미 설정된 `inputflags`는 다음 `process_input`의 `player_fix_input`이 물리 키 상태로 되돌린다(최대 1프레임, 물리 키가 눌려 있지 않으면 전부 해제).
- 새 에피소드로 넘어가면 `hold = 0`, 슬롯 비움. `episode_id`가 다른 액션은 거부한다.

### 6.3 동기 콜백 모드와 비동기 모드

- **동기 콜백:** 호스트가 `Module.taiseiAIOnFrame(frame, episode_id)`를 정의하면 브리지가 캡처 직후(★) 같은 틱 안에서 호출한다. 콜백은 `obs`를 읽고 `submit(…, frame + 1, …)`를 부른다. 이 경로는 `missing`이 생기지 않는다. 단, **정책 시간이 곧 프레임 시간에 포함된다.** 판단이 16.7 ms를 넘으면 게임 실시간이 느려질 뿐 논리 프레임은 건너뛰거나 어긋나지 않는다.
- **비동기:** 콜백을 정의하지 않고 호스트가 자체 타이머에서 `read`/`submit`을 부른다. 한 틱에 0개 또는 여러 개가 보일 수 있으며 `stale`/`dup`/`missing`이 늘 수 있다. 이 카운터가 평가의 `quality.action_sync`로 간다.
- 콜백 안에서 던진 예외는 호스트(어댑터)가 잡아서 `disable('policy_error')`를 부른다.

### 6.4 정지 중 상태 `status`

관측은 논리 프레임마다 나오므로 일시정지·메뉴 구간에는 갱신되지 않는다. 그동안 호스트가 읽는 별도의 작은 블록이다.

| 필드 | 의미 |
| --- | --- |
| `in_stage` | 스테이지 루프 안인지(1) |
| `paused` | 일시정지 또는 게임오버 메뉴가 떠 있는지 |
| `episode_id`, `last_frame` | 마지막 에피소드 번호와 마지막으로 캡처한 프레임 |
| `owner_state`, `owner_reason`, `owner_events` | `obs.meta`와 같은 값(항상 최신) |
| `replay_mode`, `gameover` | 같은 이름의 `obs.meta` 값 |
| `observe` | 관측 캡처 켜짐 여부 |

## 7. 실행 제어와 지원 현황

| 기능 | v1 | 설명 |
| --- | --- | --- |
| 관측 켜기/끄기 | 지원 | `set_observe(1)`일 때만 캡처한다. `ai_active`/`ai_suspended`에서는 자동으로 켜진다. 꺼진 기본 상태는 틱마다 분기 1개 비용뿐이다 |
| 소유권 전환 | 지원 | 4절 |
| 액션 적용 | 지원 | 6절. 리플레이 이벤트 경로 사용 |
| 재시작 | 지원 | `request_restart()`가 원본 `F2`(`KEY_RESTART`)와 같은 경로(`stage_finish(GAMEOVER_RESTART)`)를 다음 `process_input`에서 실행한다. 시드는 주입 정책을 따른다 |
| **시작** | **미지원** | 메뉴 조작·`callMain` 인자(개발자 빌드의 스테이지 직접 진입)는 세션 1 실행기와 세션 5 셸이 담당한다. 브리지가 스테이지를 시작하지 않는다 |
| 시드 지정 | **지원** | 8절 |
| **프레임 스텝** | **미지원** | 원본에는 `DEBUG` 빌드 전용 `KEY_TIMESTOP`뿐이고 릴리스에는 없다. 동기 콜백 모드가 "관측 → 같은 틱에서 액션 등록 → 다음 틱 적용"을 실시간 지연 없이 보장하므로 별도 스텝 기능이 필요 없다고 판단했다. 외부 프로세스가 프레임 단위 락스텝을 쓰려면 별도 확장이 필요하며 이 계약에 없다 |
| 퀵세이브/퀵로드 | 미지원 | 원본은 릴리스 빌드에서 **연습 모드 전용**(`is_quicksave_allowed`)이다. 브리지는 건드리지 않는다. `episode_id`는 퀵로드로 `_stage_enter`를 다시 부르면 올라간다 |
| 결정성 | **미확인** | 8.2절 |

## 8. 시드·종료·재현

### 8.1 시드

- 스테이지 진입마다 `rng_seed(&global.rand_game, seed)`가 불린다(`_stage_enter`). 새 게임은 `makeseed()`, 리플레이 재생은 기록된 시드를 쓴다.
- 브리지는 **주입 시드**를 지원한다. `set_seed(lo, hi, sticky)`로 시드를 예약하면 다음 비-리플레이 `_stage_enter`가 `makeseed()` 대신 이 값을 쓴다. 같은 `rng_seed` 호출이고 RNG는 바꾸지 않는다. 시드는 평소처럼 리플레이에 기록된다.
  - `sticky = 0`: 한 번만 쓰고 해제. `sticky = 1`: 해제할 때까지 모든 에피소드(재시작 포함)에 같은 시드를 쓴다.
  - `clear_seed()`로 해제한다. 해제하면 `makeseed()`로 돌아간다.
- 관측 `seed_lo/hi`와 `seed_source`가 이 에피소드에 실제로 쓰인 값과 출처를 알린다(평가 `config.seed.actual`/`control`: `seed_source` 0→`unsupported`가 아니라 "무작위", 1→`set`, 2→`replay`).
- 시각 효과용 `rand_visual`과 Stage 2의 배경용 `makeseed()`(`stages/stage2/draw.c`)는 게임 규칙 RNG가 아니다. 주입 대상이 아니다.

### 8.2 결정성 (미확인)

현재까지 확인한 것은 **리플레이가 시드와 입력 이벤트를 저장하고 재생하는 구조**뿐이다. 같은 시드·같은 액션 열로 반복했을 때 상태가 같은지, `EV_CHECK_DESYNC` 검증을 통과하는지는 [BRIDGE.md](BRIDGE.md)의 검증 절에 결과를 적은 뒤에만 "재현 확인"이라고 쓴다. 그 전에 평가(세션 4)는 `reproducibility: not_verified`로 고정한다.

### 8.3 종료 감지

- `meta.gameover`(`global.gameover`)와 `status.gameover`로 판단한다: `WIN`(스테이지 클리어), `DEFEAT`, `ABORT`, `RESTART`, `SCORESCREEN`(클리어 점수 화면), `TRANSITIONING`.
- 스펠 연습 스테이지의 종료: 보스가 사라지면 120프레임 뒤 `stage_finish(WIN)`이 불린다.
- 게임오버(잔기 소진) 시 컨티뉴/재시작 메뉴가 뜨며(`stage_gameover`), 이때 브리지는 `ai_suspended`(`game_over`)로 바꾼다. 스펠 연습의 자동 재시작 설정(`SPELLSTAGE_AUTORESTART`)이 켜져 있으면 메뉴 없이 `RESTART`로 넘어간다.
- 스테이지가 끝나면(`stage_finish`) `ai_suspended`(`stage_end` 또는 `restart`)가 되고 마지막으로 캡처된 관측의 `gameover`가 종료 유형을 가진다. 종료 직후의 관측은 없을 수 있다. 호스트는 `status.gameover`를 읽는다.

## 9. 원본 규칙 보존

- 브리지는 **입력 원천만 바꾼다.** 이동 속도·판정·탄막·잔기·봄은 건드리지 않는다. 무적·피격 무시·속도 변경은 어떤 API로도 불가능하다.
- AI 액션은 사람의 키와 같은 `player_event` 경로로 들어가 `global.replay.output`에 기록된다(Q2). 따라서 AI 플레이는 원본 리플레이 재생기로 다시 볼 수 있다. 리플레이 파일에는 AI 표시가 남지 않는다. 증거에 필요하면 호스트가 `episode_id`·시드·`act_*` 카운터를 별도로 저장한다.
- 규칙 보존 판정 입력: `cheat_flags`, `cheat_events`, `p_vulnerable`, `p_speed_*`. 이 값이 이상하면 평가는 그 에피소드를 `invalid / rule_violation`으로 둔다.
- 관측 캡처는 게임 상태를 쓰지 않는다(읽기 전용). 브리지가 꺼진 기본 상태에서는 게임 루프에 분기 몇 개만 더해진다.

## 10. 호스트 API (어댑터, Q1)

JS 어댑터 `ai/bridge/taisei-ai-bridge.mjs`의 소유자는 **세션 2**다. 세션 5 셸과 세션 3 정책, 세션 1 실행기는 어댑터를 불러 쓴다(세션 5의 제안과 같은 분담이다. 어댑터가 `wasmMemory` 뷰 재생성과 `layout` 해석을 맡아야 계약 위반이 한곳에서만 생긴다). 구현 세부는 [BRIDGE.md](BRIDGE.md) 참조.

```js
import { createBridge } from './taisei-ai-bridge.mjs';
const bridge = createBridge(Module);          // 레이아웃 읽기, 호환 확인
bridge.setObserve(true);
bridge.onFrame((obs, ctl) => { ctl.submit({ hold, edges }); });   // 동기 콜백
bridge.enable(); bridge.suspend('host_request'); bridge.resume(); bridge.disable('host_request');
bridge.state();            // status 블록(정지 중에도 최신)
bridge.read();             // 비동기: 현재 관측 뷰(복사 없음, 다음 캡처 전까지 유효)
bridge.snapshot();         // 복사본(보관용)
bridge.onEvent((kind, state, reasonName) => {});   // 소유권 전환 알림
bridge.setSeed(seed, { sticky }); bridge.clearSeed(); bridge.requestRestart();
```

세션 5의 호스트 API(`window.taiseiAI.*`)는 이 어댑터를 감싼다. 이름은 세션 5가 정한다.

## 11. v0.2 대비 변경·정정

| 항목 | v0.2 | v1 |
| --- | --- | --- |
| 관측 캡처 지점 | `stage_comain` 본문 끝 | `cosched_run_tasks` 직후, `global.frames++` 직전 (1절) |
| `owner_state` 전환 사유 | 이벤트 이름만 | 코드 14종 (4.2절). `dialog`는 호스트 전용 |
| `ai_suspended`의 입력 | 입력 해제(`hold = 0`) | 물리 키 그대로. AI가 입력을 쥐지 않는다는 뜻. 사람의 일시정지·점수 화면 조작이 막히지 않는다 |
| 사용자 키 | 미정 | `ai_active` 중이면 `manual`로 전환(4.3절) |
| 시작(`start`) | 계획 | 미지원 (7절) |
| 프레임 스텝 | 선택적 lockstep 검토 | 미지원, 동기 콜백으로 대체 (7절) |
| 탄 형상 필드 | `rx`, `ry` | `wx`, `wy` (지름) — v0.2에서 이미 정정한 의미를 이름에 반영 |
| 레이저 | 구간 수 | 구간이 틱 F 시점이라는 한 틱 오차 명시 (1절) |
| 결정성 | "보장" 철회 | 미확인, 검증 뒤 기록 |
