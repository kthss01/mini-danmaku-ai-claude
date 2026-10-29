// 기준선 정책 `idle`: 이동하지 않고 공격만 유지한다. 비교용이며 어떤 위험도 피하지 않는다.
// 정책 번들 형식(`taisei.ai.policy/0`)은 avoid-v1과 같다.

export const HOLD = Object.freeze({ UP: 1, DOWN: 2, LEFT: 4, RIGHT: 8, FOCUS: 16, SHOT: 32 });

export const meta = Object.freeze({
	schema: 'taisei.ai.policy/0',
	id: 'idle',
	version: '0.1.0',
	obs_schema: ['taisei.ai.obs/0'],
	act_schema: 'taisei.ai.act/0',
});

export function init(config) {
	const cfg = { shoot: true, ...(config || {}) };
	let decisions = 0;

	return {
		decide(obs) {
			decisions++;
			return {
				hold: cfg.shoot ? HOLD.SHOT : 0,
				bomb: 0,
				special: 0,
				request: null,
				meta: { mode: 'normal', frame: obs && obs.frame, safe_verified: false },
			};
		},
		reset() {},
		dispose() {},
		stats() {
			return { id: meta.id, version: meta.version, decisions };
		},
		describe() {
			return { id: meta.id, version: meta.version, config: cfg };
		},
	};
}
