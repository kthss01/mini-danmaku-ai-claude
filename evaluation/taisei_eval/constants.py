"""평가 정의에 쓰는 상수. 값의 근거는 docs/ai/EVALUATION.md와 docs/ai/CONTRACT.md(브리지 계약 v1)."""

FPS = 60

# obs.player.p_phase (CONTRACT.md 2.3)
PHASE_NORMAL, PHASE_HIT_PENDING, PHASE_DEAD, PHASE_RECOVERING, PHASE_BOMBING = 0, 1, 2, 3, 4

# obs.meta.owner_state
OWNER_NAMES = {0: "manual", 1: "ai_active", 2: "ai_suspended"}

# obs.meta.cheat_flags 비트
CHEAT_IDDQD = 1       # 비트 0
CHEAT_REPLAY_FLAG = 2  # 비트 1
CHEAT_SKIP = 4        # 비트 2
CHEAT_VIOLATION_MASK = CHEAT_IDDQD | CHEAT_REPLAY_FLAG | CHEAT_SKIP  # 비트 3(개발자 빌드)은 위반이 아니다

# obs.meta.overflow 비트
OVERFLOW_KINDS = ((1, "bullets"), (2, "lasers"), (4, "laser_segs"), (8, "enemies"))

# hold 비트 (원본 inputflags)
HOLD_UP, HOLD_DOWN, HOLD_LEFT, HOLD_RIGHT, HOLD_FOCUS, HOLD_SHOT, HOLD_SKIP = 1, 2, 4, 8, 16, 32, 64
HOLD_NAMES = ((HOLD_UP, "UP"), (HOLD_DOWN, "DOWN"), (HOLD_LEFT, "LEFT"), (HOLD_RIGHT, "RIGHT"),
              (HOLD_FOCUS, "FOCUS"), (HOLD_SHOT, "SHOT"), (HOLD_SKIP, "SKIP"))
HOLD_DIRECTIONS = HOLD_UP | HOLD_DOWN | HOLD_LEFT | HOLD_RIGHT

# 판단 지연 예산(ms). 4ms는 #22 목표값이며 실측 후 다시 정한다.
POLICY_BUDGET_MS = 4.0
FRAME_BUDGET_MS = 1000.0 / FPS

# 실행 속도: 60프레임 창의 fps가 이 값 미만이면 "느린 창"이다(60의 95%).
SIM_FPS_SLOW_THRESHOLD = 57.0
SIM_FPS_WINDOW = 60

DEFAULT_PRE_HIT_WINDOW = 120
PLAYFIELD_W, PLAYFIELD_H = 480, 560
EDGE_MARGIN = 24.0

NOT_EVALUABLE_OK = ("completed",)
