// 정책 설정 기본값과 검증. 병합된 최종 값은 policy.describe().config로 노출돼
// 평가(#23)의 params_sha256 대상이 된다.

// 액션 비트. 계약 `taisei.ai.act/1`(docs/ai/CONTRACT.md 6.1절)과 같다.
export const HOLD = Object.freeze({ UP: 1, DOWN: 2, LEFT: 4, RIGHT: 8, FOCUS: 16, SHOT: 32, SKIP: 64 });
export const EDGE = Object.freeze({ BOMB: 1, SPECIAL: 2 });

export const DEFAULT_CONFIG = Object.freeze({
	horizon: 30,            // 예측 프레임 수(0.5초)
	budget_ms: 4,           // 정책 단독 판단 예산(실측 전 목표값, #22 v0.1)
	work_limit: 0,          // 결정적 작업량 상한(0이면 끔). 테스트에서 예산 초과를 재현할 때 쓴다
	shoot: true,            // 공격 유지(HOLD.SHOT을 계속 요청)
	gamma: 0.92,            // 먼 미래 위험의 할인율
	comfort: 14,            // 이 거리(px) 안으로 탄이 오면 여유 비용이 생긴다
	weights: {
		clear: 1.0,         // 여유거리 비용
		deadend: 1.2,       // 막다른 곳 벌점
		turn: 1.0,          // 방향 전환 벌점
		pos: 0.6,           // 위치 선호(공격 유지용, 약하게)
		stick: 0.6,         // 직전 행동 유지 보너스(진동 억제)
	},
	// 안전 여유 [m0, k]: 시점 t에서 m(t) = m0 + k·t (px). 탄 크기에 더해진다
	margin: {
		exact: [0.75, 0.05],   // MoveParams 전개, 직전 이동이 규칙과 일치
		recent: [1.25, 0.15],  // 최근에 규칙 위반이 한 번 있었음
		extrap: [1.5, 0.3],    // 직선 외삽(MoveParams 없음·NOMOVE·규칙 위반 반복)
		laser: [1.0, 0.15],    // 레이저는 현재 형상 유지로 가정
		enemy: [1.0, 0.5],     // 적은 현재 위치 유지로 가정
		laser_unknown_extra: 6, // 활성 시점을 모르는 충전 중 레이저에 더하는 반지름
	},
	trust: {
		err_threshold: 0.05,   // 직전 이동이 MoveParams 규칙과 이 값(px) 넘게 어긋나면 위반
		recent_frames: 8,      // 위반 후 이 프레임 동안은 recent
		chaos_window: 60,      // 이 구간에 위반이 chaos_count회 이상이면 extrap
		chaos_count: 3,
	},
	rollout_stop_after: [4, 8, 16], // 같은 행동을 k프레임 한 뒤 정지하는 롤아웃
	max_relevant: 384,      // 정밀 평가할 탄 최대 수(넘으면 가까운 순, 보수 동작)
	max_laser_segs: 256,
	overflow_margin_scale: 2, // overflow 프레임에서 안전 여유 배율(보수 동작)
	on_frame_gap: 'halt',   // 프레임 번호가 건너뛰면 'halt'(입력 해제) 또는 'reset'
	deadline_suspend_after: 10, // 예산 초과 halt가 연속 이 횟수면 suspend 요청(0이면 안 함)
	bomb: {
		enabled: false,       // 봄은 기본 꺼짐. 켜면 사용 기록이 stats().bombs에 남는다
		trigger_frames: 8,    // 모든 후보가 이 프레임 안에 확정 피격이면 사용
		deathbomb: false,     // 데스봄 유예 창(phase=hit_pending)에서 사용
		max_per_episode: 1,
	},
	pos_pref: { y: 460 },   // 선호하는 세로 위치(아래쪽)
	trace: 0,               // 0보다 크면 최근 N프레임의 결정 요약을 보관(피격 전 원인 분석용)
});

function isObject(v) {
	return v !== null && typeof v === 'object' && !Array.isArray(v);
}

function merge(base, over, path) {
	const out = {};

	for (const key of Object.keys(base)) {
		const b = base[key];
		const o = over ? over[key] : undefined;

		if (o === undefined) {
			out[key] = Array.isArray(b) ? b.slice() : isObject(b) ? merge(b, undefined, `${path}${key}.`) : b;
		} else if (isObject(b)) {
			if (!isObject(o)) {
				throw new Error(`config.${path}${key}: 객체여야 한다`);
			}
			out[key] = merge(b, o, `${path}${key}.`);
		} else if (Array.isArray(b)) {
			const variable = key === 'rollout_stop_after';

			if (!Array.isArray(o) || (!variable && o.length !== b.length) || !o.every(Number.isFinite)) {
				throw new Error(`config.${path}${key}: 숫자 ${b.length}개 배열이어야 한다`);
			}
			out[key] = o.slice();
		} else if (typeof o !== typeof b || (typeof o === 'number' && !Number.isFinite(o))) {
			throw new Error(`config.${path}${key}: ${typeof b} 값이어야 한다`);
		} else {
			out[key] = o;
		}
	}

	if (over) {
		for (const key of Object.keys(over)) {
			if (!(key in base)) {
				throw new Error(`config.${path}${key}: 알 수 없는 설정`);
			}
		}
	}

	return out;
}

export function resolveConfig(user) {
	if (user !== undefined && user !== null && !isObject(user)) {
		throw new Error('config: 객체여야 한다');
	}

	const cfg = merge(DEFAULT_CONFIG, user || undefined, '');

	if (!Number.isInteger(cfg.horizon) || cfg.horizon < 4 || cfg.horizon > 120) {
		throw new Error('config.horizon: 4~120 정수여야 한다');
	}
	if (!(cfg.budget_ms > 0)) {
		throw new Error('config.budget_ms: 0보다 커야 한다');
	}
	if (cfg.on_frame_gap !== 'halt' && cfg.on_frame_gap !== 'reset') {
		throw new Error("config.on_frame_gap: 'halt' 또는 'reset'이어야 한다");
	}
	if (!cfg.rollout_stop_after.every(k => Number.isInteger(k) && k >= 1)) {
		throw new Error('config.rollout_stop_after: 1 이상 정수 배열이어야 한다(0 이하는 정지 롤아웃과 구분되지 않는다)');
	}
	if (!Number.isInteger(cfg.max_relevant) || cfg.max_relevant < 1) {
		throw new Error('config.max_relevant: 1 이상 정수여야 한다');
	}
	if (!Number.isInteger(cfg.trace) || cfg.trace < 0) {
		throw new Error('config.trace: 0 이상 정수여야 한다');
	}

	return cfg;
}
