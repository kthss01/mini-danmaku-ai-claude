// 기준선 정책 `simple-move`: 관측과 무관하게 일정 주기로 좌우로 왕복하며 공격을 유지한다.
// 회피 정책과 같은 조건에서 비교하기 위한 것이며 탄을 보지 않는다.
// 정책 번들 형식(`taisei.ai.policy/0`)은 avoid-v1과 같다.

export const HOLD = Object.freeze({ UP: 1, DOWN: 2, LEFT: 4, RIGHT: 8, FOCUS: 16, SHOT: 32, SKIP: 64 });

export const meta = Object.freeze({
	schema: 'taisei.ai.policy/0',
	id: 'simple-move',
	version: '0.1.0',
	obs_schema: ['taisei.ai.obs/1'],
	act_schema: 'taisei.ai.act/1',
});

export function init(config) {
	const cfg = { shoot: true, half_period: 45, ...(config || {}) };

	if (!Number.isInteger(cfg.half_period) || cfg.half_period < 1) {
		throw new Error('config.half_period: 1 이상 정수여야 한다');
	}

	let decisions = 0;
	let start = null; // 에피소드 첫 관측 프레임

	return {
		decide(obs) {
			decisions++;

			if (start === null) {
				start = obs.meta.frame;
			}

			// 주기마다 방향을 바꾼다. 위치와 무관해서 벽에서는 제자리에 눌려 있게 된다
			const phase = Math.floor((obs.meta.frame - start) / cfg.half_period) % 2;
			return {
				hold: (phase === 0 ? HOLD.RIGHT : HOLD.LEFT) | (cfg.shoot ? HOLD.SHOT : 0),
				edges: 0,
				request: null,
				meta: { mode: 'normal', frame: obs.meta.frame, safe_verified: false },
			};
		},
		reset() {
			start = null;
		},
		dispose() {},
		stats() {
			return { id: meta.id, version: meta.version, decisions };
		},
		describe() {
			return { id: meta.id, version: meta.version, config: cfg };
		},
	};
}
