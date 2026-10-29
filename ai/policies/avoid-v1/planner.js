// 후보 행동 17개(정지 + 8방향 × {보통, 저속})를 롤아웃으로 평가해 하나를 고른다.
//
// 평가 순서(#22 v0.1): ① 모든 후보의 피격 여부 → ② 여유거리 → ③ 막다른 곳 → ④ 방향 유지·위치 선호.
// 예산이 끊기면 ①을 끝낸 안전 후보 중에서만 고른다. ①이 끝나지 않은 후보는 안전으로 고르지 않는다.

import { clampX, clampY, VIEW_W, VIEW_H } from './geometry.js';
import { HIT_NONE, HIT_EXACT } from './scene.js';

const S2 = Math.SQRT1_2;

// 인덱스 0은 정지, 1..8은 위에서 시계 방향. 좌표계는 y가 아래로 증가한다.
const DIRS = [
	[0, 0], [0, -1], [S2, -S2], [1, 0], [S2, S2], [0, 1], [-S2, S2], [-1, 0], [-S2, -S2],
];
const DIR_BITS = [
	[0, 0, 0, 0], // [up, down, left, right]
	[1, 0, 0, 0], [1, 0, 0, 1], [0, 0, 0, 1], [0, 1, 0, 1], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [1, 0, 1, 0],
];
export const NUM_CAND = 17;

export function candDir(c) {
	return c === 0 ? 0 : ((c - 1) % 8) + 1;
}

export function candFocus(c) {
	return c >= 9;
}

export function candName(c) {
	const names = ['stop', 'U', 'UR', 'R', 'DR', 'D', 'DL', 'L', 'UL'];
	return names[candDir(c)] + (c >= 9 ? '-focus' : '');
}

export function candHoldBits(c, HOLD) {
	const [u, d, l, r] = DIR_BITS[candDir(c)];
	return (u ? HOLD.UP : 0) | (d ? HOLD.DOWN : 0) | (l ? HOLD.LEFT : 0) | (r ? HOLD.RIGHT : 0) | (c >= 9 ? HOLD.FOCUS : 0);
}

export class Planner {
	constructor(cfg, scene, host) {
		this.cfg = cfg;
		this.scene = scene;
		this.host = host;
		this.H = cfg.horizon;
		const W = this.H + 1;

		// 후보별 롤아웃 경로(viable한 것 하나)
		this.pathX = new Float64Array(NUM_CAND * W);
		this.pathY = new Float64Array(NUM_CAND * W);
		this.tmpX = new Float64Array(W);
		this.tmpY = new Float64Array(W);

		this.sM = new Int32Array(NUM_CAND);     // 가장 좋은 롤아웃의 첫 여유 침범 시점(H+1이면 없음)
		this.sE = new Int32Array(NUM_CAND);     // 같은 롤아웃의 첫 확정 피격 시점
		this.bestK = new Int32Array(NUM_CAND);  // 가장 좋은 롤아웃에서 이동을 유지하는 프레임 수
		this.done1 = new Uint8Array(NUM_CAND);  // ① 완료
		this.cost = new Float64Array(NUM_CAND);
		this.costDone = new Uint8Array(NUM_CAND);

		this.prev = -1;       // 직전 선택 후보
		this.prevK = 0;       // 직전 롤아웃에서 남은 이동 프레임
		this.planValid = false;
		this.work = 0;
		this.t0 = 0;
		this.overBudget = false;
		this.holdFrames = 0;
	}

	reset() {
		this.prev = -1;
		this.prevK = 0;
		this.planValid = false;
		this.holdFrames = 0;
	}

	_over() {
		if (this.cfg.work_limit > 0 && this.work > this.cfg.work_limit) {
			return true;
		}
		return this.host.now() - this.t0 > this.cfg.budget_ms;
	}

	// 후보 c를 k프레임 유지한 뒤 정지하는 롤아웃을 평가한다. 결과는 this._sM/_sE와 tmp 경로.
	_rollout(c, k, sp, P) {
		const sc = this.scene;
		const H = this.H;
		const d = DIRS[candDir(c)];
		const step = sp;
		let x = P.x;
		let y = P.y;
		let sM = H + 1;
		let sE = H + 1;
		this.tmpX[0] = x;
		this.tmpY[0] = y;
		const perStep = sc.nb + sc.nl + sc.ne + 1;

		for (let t = 1; t <= H; t++) {
			const nx = t <= k ? clampX(x + d[0] * step) : x;
			const ny = t <= k ? clampY(y + d[1] * step) : y;
			const code = sc.stepEval(t, x, y, nx, ny, false);
			this.work += perStep;
			x = nx;
			y = ny;
			this.tmpX[t] = x;
			this.tmpY[t] = y;

			if (code !== HIT_NONE) {
				if (sM > H) {
					sM = t;
				}
				if (code === HIT_EXACT) {
					sE = t;
					// 경로 나머지는 정지로 채운다(비용 계산에 쓰지 않음)
					for (let u = t + 1; u <= H; u++) {
						this.tmpX[u] = x;
						this.tmpY[u] = y;
					}
					break;
				}
			}
		}

		this._sM = sM;
		this._sE = sE;
	}

	_store(c, k, sM, sE) {
		const W = this.H + 1;
		this.pathX.set(this.tmpX, c * W);
		this.pathY.set(this.tmpY, c * W);
		this.sM[c] = sM;
		this.sE[c] = sE;
		this.bestK[c] = k;
	}

	// ① 후보 c의 롤아웃을 평가해 가장 좋은 것을 저장한다. plan=true면 이전 계획의 다음 단계도 평가한다.
	_phase1Candidate(c, sp, P) {
		const H = this.H;
		const ks = [];

		if (c === this.prev && this.planValid && this.prevK > 0) {
			ks.push(this.prevK); // 이전 계획의 다음 단계
		}

		if (c === 0) {
			ks.push(0);
		} else {
			ks.push(H);

			for (const s of this.cfg.rollout_stop_after) {
				if (s < H && !ks.includes(s)) {
					ks.push(s);
				}
			}
		}

		let bestE = -1;
		let bestM = -1;
		let any = false;

		for (const k of ks) {
			this._rollout(c, k, sp, P);

			if (this._sE > bestE || (this._sE === bestE && this._sM > bestM)) {
				bestE = this._sE;
				bestM = this._sM;
				this._store(c, k, bestM, bestE);
				any = true;
			}

			if (bestE > H && bestM > H) {
				break; // 안전한 롤아웃을 찾았다
			}

			if (this._over()) {
				// 이 후보의 확인이 끝나지 않았다: 안전한 롤아웃을 찾지 못한 채 중단
				return false;
			}
		}

		return any;
	}

	_costOf(c, v) {
		const sc = this.scene;
		const H = this.H;
		const W = H + 1;
		const w = this.cfg.weights;
		const gamma = this.cfg.gamma;
		const P = v.player;
		// ② 여유거리
		sc.hz = 0;
		let clear = 0;
		let g = 1;

		for (let t = 1; t <= H; t++) {
			const before = sc.hz;
			sc.stepEval(t, this.pathX[c * W + t - 1], this.pathY[c * W + t - 1], this.pathX[c * W + t], this.pathY[c * W + t], true);
			clear += g * (sc.hz - before);
			g *= gamma;
		}

		this.work += H * (sc.nb + sc.nl + sc.ne + 1);
		this.cost[c] = w.clear * clear;

		if (this._over()) {
			return false;
		}

		// ③ 막다른 곳: 6프레임 뒤 위치에서 다음 한 걸음이 안전한 후보 수
		const te = Math.min(6, H - 1);
		const ex = this.pathX[c * W + te];
		const ey = this.pathY[c * W + te];
		let exits = 0;

		for (let m = 0; m < NUM_CAND; m++) {
			const d = DIRS[candDir(m)];
			const s = candFocus(m) ? P.speed_focus : P.speed_normal;
			const nx = clampX(ex + d[0] * s);
			const ny = clampY(ey + d[1] * s);

			if (sc.stepEval(te + 1, ex, ey, nx, ny, false) === HIT_NONE) {
				exits++;
			}
		}

		this.work += NUM_CAND * (sc.nb + sc.nl + sc.ne + 1);
		const lack = Math.max(0, 6 - exits);
		this.cost[c] += w.deadend * (lack * lack) / 6;

		if (this._over()) {
			return false;
		}

		// ④ 방향 전환 벌점·직전 행동 유지·위치 선호 (계산이 가벼워 항상 끝낸다)
		this.cost[c] += w.turn * this._turn(c);

		if (c === this.prev) {
			this.cost[c] -= w.stick;
		}

		const tp = Math.min(12, H);
		const tx = v.bossX === undefined ? VIEW_W * 0.5 : v.bossX;
		const pos = Math.abs(this.pathX[c * W + tp] - tx) / (VIEW_W * 0.5) +
			Math.abs(this.pathY[c * W + tp] - this.cfg.pos_pref.y) / (VIEW_H * 0.5);
		this.cost[c] += w.pos * pos;
		return true;
	}

	_turn(c) {
		if (this.prev < 0 || c === this.prev) {
			return 0;
		}

		const a = DIRS[candDir(c)];
		const b = DIRS[candDir(this.prev)];
		const dot = a[0] * b[0] + a[1] * b[1];
		let t = 0.4;

		if (dot < -0.01) {
			t = 1.0; // 반대 방향으로 급변
		} else if (candDir(c) === 0 || candDir(this.prev) === 0) {
			t = 0.5;
		}

		if (candFocus(c) !== candFocus(this.prev)) {
			t += 0.15;
		}

		return t;
	}

	// 반환: { c, mode, complete, sE, sM, bomb }
	decide(v) {
		const sc = this.scene;
		const H = this.H;
		const P = v.player;
		this.work = 0;
		this.overBudget = false;
		this.done1.fill(0);
		this.costDone.fill(0);
		this.sM.fill(H + 1);
		this.sE.fill(H + 1);

		// 평가 순서: 이전 행동, 정지, 나머지
		const order = [];

		if (this.prev >= 0) {
			order.push(this.prev);
		}
		if (this.prev !== 0) {
			order.push(0);
		}
		for (let c = 1; c < NUM_CAND; c++) {
			if (c !== this.prev) {
				order.push(c);
			}
		}

		let finished = true;

		for (let i = 0; i < order.length; i++) {
			const c = order[i];
			const sp = candFocus(c) ? P.speed_focus : P.speed_normal;
			const ok = this._phase1Candidate(c, sp, P);
			this.done1[c] = ok ? 1 : 0;

			if (!ok) {
				// 이 후보의 ①이 끝나지 않았다
				this.overBudget = true;
				finished = false;
				break;
			}

			if (this._over()) {
				this.overBudget = true;

				if (i !== order.length - 1) {
					finished = false;
				}
				break;
			}
		}

		const viable = [];

		for (let c = 0; c < NUM_CAND; c++) {
			if (this.done1[c] && this.sE[c] > H && this.sM[c] > H) {
				viable.push(c);
			}
		}

		let pool = viable;
		let mode = 'normal';

		if (viable.length === 0) {
			if (!finished) {
				// ② 이전 계획의 다음 단계를 현재 관측으로 ①만 다시 확인한다
				const reuse = this._tryReuse(P);

				if (reuse >= 0) {
					return { c: reuse, mode: 'reuse', complete: false, sE: H + 1, sM: H + 1, bomb: false, overBudget: true };
				}

				return { c: -1, mode: 'halt', complete: false, sE: H + 1, sM: H + 1, bomb: false, overBudget: true };
			}

			// 안전한 후보가 없다: 가장 늦게 맞는 쪽(확정 피격 → 여유 침범 순)을 고른다
			let bestE = -1;
			let bestM = -1;

			for (let c = 0; c < NUM_CAND; c++) {
				if (this.done1[c] && (this.sE[c] > bestE || (this.sE[c] === bestE && this.sM[c] > bestM))) {
					bestE = this.sE[c];
					bestM = this.sM[c];
				}
			}

			pool = [];

			for (let c = 0; c < NUM_CAND; c++) {
				if (this.done1[c] && this.sE[c] === bestE && this.sM[c] === bestM) {
					pool.push(c);
				}
			}

			mode = bestE > H ? 'risky' : 'doomed';
		}

		// ② ③ ④ 비용 (예산 안에서). 이전 행동, 정지, 나머지 순으로 계산한다
		pool = pool.slice().sort((a, b) => order.indexOf(a) - order.indexOf(b));
		let complete = true;

		for (const c of pool) {
			if (this._over()) {
				this.overBudget = true;
				complete = false;
				break;
			}

			this.costDone[c] = this._costOf(c, v) ? 1 : 0;

			if (!this.costDone[c]) {
				complete = false;
			}
		}

		// 선택: 비용을 끝낸 후보 중 최소, 없으면 ①만 끝낸 후보 중 이전 행동 → 정지 → 첫 번째
		let pick = -1;
		let best = Infinity;

		for (const c of pool) {
			if (this.costDone[c] && this.cost[c] < best) {
				best = this.cost[c];
				pick = c;
			}
		}

		if (pick < 0) {
			complete = false;
			pick = pool.includes(this.prev) ? this.prev : pool.includes(0) ? 0 : pool[0];
		}

		// 봄 판단(기본 꺼짐): 확정 피격을 피할 후보가 없고 곧 맞을 때
		let bomb = false;
		const bc = this.cfg.bomb;

		if (bc.enabled && mode === 'doomed' && this.sE[pick] <= bc.trigger_frames && P.bombs > 0 && P.phase === 'normal') {
			bomb = true;
		}

		return { c: pick, mode, complete, sE: this.sE[pick], sM: this.sM[pick], bomb, overBudget: this.overBudget };
	}

	// 이전 계획의 다음 단계가 현재 관측에서도 확정·여유 피격이 없으면 그 후보를 돌려준다
	_tryReuse(P) {
		const H = this.H;

		if (!this.planValid || this.prev < 0) {
			return -1;
		}

		const c = this.prev;
		const sp = candFocus(c) ? P.speed_focus : P.speed_normal;
		this._rollout(c, c === 0 ? 0 : this.prevK, sp, P);

		if (this._sE > H && this._sM > H) {
			this._store(c, this.prevK, this._sM, this._sE);
			return c;
		}

		return -1;
	}

	// 선택 결과를 계획 상태에 반영한다
	commit(c, k) {
		if (c === this.prev) {
			this.holdFrames++;
		} else {
			this.holdFrames = 1;
		}

		this.prev = c;
		this.prevK = c === 0 ? 0 : Math.max(0, k - 1);
		this.planValid = true;
	}

	chosenK(c) {
		return this.bestK[c];
	}
}
