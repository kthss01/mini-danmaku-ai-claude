// 충돌 예측·자동 회피 기준선 정책 `avoid-v1` (이슈 #22).
// 정책 번들 형식은 docs/ai/POLICY.md, 이슈 #22의 Q5 답변(`taisei.ai.policy/0`)을 따른다.
// 이 모듈은 DOM·Node API·네트워크·Math.random·Date를 쓰지 않는다. 시간은 host.now()로만 읽는다.

import { HOLD, resolveConfig } from './config.js';
import { validateObs, SUPPORTED_OBS_SCHEMAS } from './input.js';
import { Scene } from './scene.js';
import { Planner, candHoldBits, candName } from './planner.js';

export { HOLD };

export const meta = Object.freeze({
	schema: 'taisei.ai.policy/0',
	id: 'avoid-v1',
	version: '0.1.0',
	obs_schema: SUPPORTED_OBS_SCHEMAS,
	act_schema: 'taisei.ai.act/0',
});

const FRAME_BUDGET_MS = 1000 / 60;
const MAX_SAMPLES = 100000;

function percentile(sorted, p) {
	if (sorted.length === 0) {
		return 0;
	}
	const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1));
	return sorted[idx];
}

export function init(config, host) {
	const cfg = resolveConfig(config);
	const now = host && typeof host.now === 'function' ? host.now : () => performance.now();
	const scene = new Scene(cfg);
	const planner = new Planner(cfg, scene, { now });

	let disposed = false;
	let lastFrame = -1;
	let lastEpisode = null;
	let consecutiveHalts = 0;
	let bombUses = 0;

	const stats = {
		decisions: 0,
		modes: {},
		halts: { total: 0, by_reason: {} },
		conservative_frames: 0,
		over_policy_budget: 0,
		over_frame_budget: 0,
		pred_fail: 0,
		suspend_requests: 0,
		bombs: [],
		max_ms: 0,
	};
	const samples = [];
	const traceBuf = [];

	function resetState() {
		planner.reset();
		scene.resetTrust();
		consecutiveHalts = 0;
		bombUses = 0;
	}

	function record(ms, mode, frame, extra) {
		stats.decisions++;
		stats.modes[mode] = (stats.modes[mode] || 0) + 1;

		if (ms > cfg.budget_ms) {
			stats.over_policy_budget++;
		}
		if (ms > FRAME_BUDGET_MS) {
			stats.over_frame_budget++;
		}
		if (ms > stats.max_ms) {
			stats.max_ms = ms;
		}
		if (samples.length < MAX_SAMPLES) {
			samples.push(ms);
		}
		if (cfg.trace > 0) {
			traceBuf.push({ frame, mode, ms: Math.round(ms * 1000) / 1000, ...extra });

			if (traceBuf.length > cfg.trace) {
				traceBuf.shift();
			}
		}
	}

	function makeHalt(frame, reason, ms) {
		stats.halts.total++;
		stats.halts.by_reason[reason] = (stats.halts.by_reason[reason] || 0) + 1;
		consecutiveHalts++;

		let request = { type: 'release', reason };

		if (reason === 'policy_deadline' && cfg.deadline_suspend_after > 0 && consecutiveHalts >= cfg.deadline_suspend_after) {
			request = { type: 'suspend', reason };
			stats.suspend_requests++;
		}

		record(ms, 'halt', frame, { reason });
		return {
			hold: 0,
			bomb: 0,
			special: 0,
			request,
			meta: { mode: 'halt', frame, reason, safe_verified: false, decision_ms: ms, over_budget: ms > cfg.budget_ms },
		};
	}

	function neutral(frame, mode, bomb, ms, extra) {
		record(ms, mode, frame, extra);
		return {
			hold: cfg.shoot ? HOLD.SHOT : 0,
			bomb: bomb ? 1 : 0,
			special: 0,
			request: null,
			meta: { mode, frame, safe_verified: false, decision_ms: ms, over_budget: ms > cfg.budget_ms },
		};
	}

	const policy = {
		decide(obs) {
			const t0 = now();

			if (disposed) {
				return makeHalt(obs && Number.isInteger(obs.frame) ? obs.frame : -1, 'disposed', 0);
			}

			const v = validateObs(obs);

			if (!v.ok) {
				resetState();
				lastFrame = -1;
				return makeHalt(obs && Number.isInteger(obs.frame) ? obs.frame : -1, 'observation_invalid', now() - t0);
			}

			const frame = v.frame;

			// 에피소드 경계·되감기: 내부 상태를 처음 값으로
			if (lastEpisode === null || v.episode !== lastEpisode || frame <= lastFrame) {
				resetState();
			} else if (frame !== lastFrame + 1) {
				// 관측 누락: 추적 기록을 믿을 수 없다
				resetState();
				lastFrame = frame;
				lastEpisode = v.episode;

				if (cfg.on_frame_gap === 'halt') {
					return makeHalt(frame, 'frame_gap', now() - t0);
				}
			}

			lastFrame = frame;
			lastEpisode = v.episode;

			const P = v.player;

			// 사망 처리 중·데스봄 유예: 움직일 수 없으므로 회피 계산을 쉰다
			if (P.phase === 'dead') {
				consecutiveHalts = 0;
				return neutral(frame, 'dead_wait', false, now() - t0);
			}

			if (P.phase === 'hit_pending') {
				consecutiveHalts = 0;
				const bc = cfg.bomb;

				if (bc.enabled && bc.deathbomb && P.bombs > 0 && bombUses < bc.max_per_episode) {
					bombUses++;
					stats.bombs.push({ frame, kind: 'deathbomb', bombs_before: P.bombs, reason: 'hit_pending' });
					return neutral(frame, 'deathbomb', true, now() - t0);
				}

				return neutral(frame, 'dead_wait', false, now() - t0);
			}

			const mscale = v.overflow !== 0 ? cfg.overflow_margin_scale : 1;
			scene.build(v, mscale);
			stats.pred_fail += scene.predFail;

			if (frame % 60 === 0) {
				scene.sweepTrust(frame);
			}

			planner.t0 = t0;
			const r = planner.decide(v);
			const ms = now() - t0;

			if (r.c < 0) {
				planner.reset();
				return makeHalt(frame, 'policy_deadline', ms);
			}

			consecutiveHalts = 0;
			const k = planner.chosenK(r.c);
			planner.commit(r.c, k);

			let bomb = 0;

			if (r.bomb && bombUses < cfg.bomb.max_per_episode) {
				bomb = 1;
				bombUses++;
				stats.bombs.push({
					frame, kind: 'policy', bombs_before: P.bombs, reason: 'all_candidates_hit',
					predicted_hit_frame: frame + r.sE, choice: candName(r.c),
				});
			}

			const conservative = v.overflow !== 0 || scene.truncated;

			if (conservative) {
				stats.conservative_frames++;
			}

			const mode = conservative ? 'conservative' : r.mode;
			const verified = !conservative && (r.mode === 'normal' || r.mode === 'reuse');
			record(ms, mode, frame, { choice: candName(r.c), plan_mode: r.mode, s_exact: r.sE, s_margin: r.sM });

			return {
				hold: candHoldBits(r.c, HOLD) | (cfg.shoot ? HOLD.SHOT : 0),
				bomb,
				special: 0,
				request: null,
				meta: {
					mode,
					plan_mode: r.mode,
					frame,
					safe_verified: verified,
					choice: candName(r.c),
					s_exact: r.sE,
					s_margin: r.sM,
					complete: r.complete,
					relevant: scene.nb,
					decision_ms: ms,
					over_budget: r.overBudget || ms > cfg.budget_ms,
				},
			};
		},

		reset(reason) {
			void reason;
			resetState();
			lastFrame = -1;
			lastEpisode = null;
		},

		dispose() {
			disposed = true;
			resetState();
		},

		stats() {
			const sorted = samples.slice().sort((a, b) => a - b);
			return {
				id: meta.id,
				version: meta.version,
				decisions: stats.decisions,
				modes: { ...stats.modes },
				halts: { total: stats.halts.total, by_reason: { ...stats.halts.by_reason } },
				suspend_requests: stats.suspend_requests,
				conservative_frames: stats.conservative_frames,
				pred_fail: stats.pred_fail,
				bombs: stats.bombs.map(b => ({ ...b })),
				decision_ms: {
					n: sorted.length,
					p50: percentile(sorted, 0.5),
					p95: percentile(sorted, 0.95),
					max: stats.max_ms,
					over_policy_budget: stats.over_policy_budget,
					over_frame_budget: stats.over_frame_budget,
				},
			};
		},

		trace() {
			return traceBuf.slice();
		},

		describe() {
			return { id: meta.id, version: meta.version, config: JSON.parse(JSON.stringify(cfg)) };
		},
	};

	return policy;
}
