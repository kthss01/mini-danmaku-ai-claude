// 한 프레임의 관측에서 "플레이어 주변에서 의미 있는 위험"만 골라 미래 위치를 전개하고,
// 플레이어의 한 걸음(선분)이 그 위험과 닿는지 판정하는 모듈.
//
// 시간 표기: 관측은 프레임 F(레이저 처리 직후). t=1은 프레임 F+1이며, 그 프레임에서
// 입력 → 플레이어 이동 → 탄 이동 → 충돌 판정 순서로 진행된다(원본 stage_comain).
// 따라서 t번째 판정 선분은 탄 기준 상대 좌표로
//   a = P(t-1) − Q(t-1),  b = P(t) − Q(t)
// 이며(원본 calc_projectile_collision의 `plr.pos − plr.velocity − prevpos` → `plr.pos − pos`),
// Q(t-1), Q(t)는 탄의 t-1, t번째 프레임 끝 위치다.

import { segOriginDist2, ucapsuleDist, segSegIntersect } from './geometry.js';

const MODE_EXACT = 0;
const MODE_RECENT = 1;
const MODE_EXTRAP = 2;

export const HIT_NONE = 0;
export const HIT_MARGIN = 1; // 안전 여유 안쪽(예측 오차 때문에 위험으로 본다)
export const HIT_EXACT = 2;  // 원본 판정과 같은 식으로 확정 피격

export class Scene {
	constructor(cfg) {
		this.cfg = cfg;
		this.H = cfg.horizon;
		const R = cfg.max_relevant;
		const W = this.H + 1;

		this.trajX = new Float64Array(R * W);
		this.trajY = new Float64Array(R * W);
		this.bCos = new Float64Array(R);
		this.bSin = new Float64Array(R);
		this.bRatio = new Float64Array(R);
		this.bRad = new Float64Array(R);
		this.bRmax = new Float64Array(R);
		this.bCirc = new Uint8Array(R);
		this.bM0 = new Float64Array(R);
		this.bK = new Float64Array(R);
		this.bLo = new Int32Array(R);
		this.bHi = new Int32Array(R);
		this.bMode = new Uint8Array(R);

		const L = cfg.max_laser_segs;
		this.lAx = new Float64Array(L);
		this.lAy = new Float64Array(L);
		this.lBx = new Float64Array(L);
		this.lBy = new Float64Array(L);
		this.lRa = new Float64Array(L);
		this.lRb = new Float64Array(L);
		this.lAct = new Int32Array(L);
		this.lExtra = new Float64Array(L); // 시점과 무관한 추가 여유(활성 시점을 모르는 충전 중 레이저)
		this.lVax = new Float64Array(L);   // 끝점의 프레임당 이동량(직전 관측과 비교)
		this.lVay = new Float64Array(L);
		this.lVbx = new Float64Array(L);
		this.lVby = new Float64Array(L);
		this.lK = new Float64Array(L);     // 시점에 비례하는 추가 여유 기울기
		this.lQ = new Float64Array(L);     // 시점 제곱에 비례하는 추가 여유(곡선·회전 오차)
		this.laserPrev = new Map();        // 레이저 id → 직전 프레임의 세그먼트 끝점
		this.laserWidth = new Map();       // 레이저 id → 직전 관측의 {frame, width} (충전 중 활성 시점 추정)

		this.eX = new Float64Array(256);
		this.eY = new Float64Array(256);
		this.eR = new Float64Array(256);

		this.cand = new Int32Array(1024);
		this.candD = new Float64Array(1024);

		this.nb = 0;
		this.nl = 0;
		this.ne = 0;
		this.mscale = 1;
		this.tVuln = 1;
		this.truncated = false;
		this.predFail = 0; // 이번 프레임에 규칙 위반이 관측된 근처 탄 수
		this.trust = new Map(); // 탄 id → 최근 규칙 위반 프레임 목록
		this.hz = 0;
	}

	resetTrust() {
		this.trust.clear();
		this.laserPrev.clear();
		this.laserWidth.clear();
	}

	// 규칙 위반 기록. id가 없으면 이번 프레임에만 recent로 본다
	_classify(id, hasId, violated, frame) {
		const t = this.cfg.trust;
		let rec = hasId ? this.trust.get(id) : undefined;

		if (violated) {
			this.predFail++;

			if (hasId) {
				if (!rec) {
					rec = [];
					this.trust.set(id, rec);
				}
				if (rec.length === 0 || rec[rec.length - 1] !== frame) {
					rec.push(frame);
				}
			}
		}

		if (!rec) {
			return violated ? MODE_RECENT : MODE_EXACT;
		}

		while (rec.length > 0 && frame - rec[0] > t.chaos_window) {
			rec.shift();
		}

		if (rec.length >= t.chaos_count) {
			return MODE_EXTRAP;
		}
		if (rec.length > 0 && frame - rec[rec.length - 1] <= t.recent_frames) {
			return MODE_RECENT;
		}
		return MODE_EXACT;
	}

	sweepTrust(frame) {
		const w = this.cfg.trust.chaos_window;

		for (const [id, rec] of this.trust) {
			if (rec.length === 0 || frame - rec[rec.length - 1] > w) {
				this.trust.delete(id);
			}
		}
	}

	// 관측 v를 해석해 위험 목록을 만든다. 반환값: 불완전 여부는 this.truncated
	build(v, mscale) {
		const cfg = this.cfg;
		const H = this.H;
		const W = H + 1;
		const P = v.player;
		const px0 = P.x;
		const py0 = P.y;
		const vmax = P.speed_normal;
		const reach = vmax * H;
		const b = v.bullets;
		const n = b.n;
		const frame = v.frame;

		this.mscale = mscale;
		this.truncated = false;
		this.predFail = 0;

		// 이 프레임 이후 피격 가능해지는 시점(상대 프레임). 그 전의 피격은 점수에 넣지 않는다.
		const until = Math.max(P.recoverytime, P.bomb_endtime, P.respawntime, P.deathtime + 1);
		this.tVuln = Math.max(1, until - frame);

		// 1단계: 도달 가능 거리 안의 탄을 거칠게 고른다
		if (this.cand.length < n) {
			this.cand = new Int32Array(n);
			this.candD = new Float64Array(n);
		}

		const mMax = Math.max(cfg.margin.exact[0] + cfg.margin.exact[1] * H,
			cfg.margin.recent[0] + cfg.margin.recent[1] * H,
			cfg.margin.extrap[0] + cfg.margin.extrap[1] * H) * mscale + 4;
		const hasMove = v.hasMove;
		const hasAttr = v.hasAttr;
		let nc = 0;

		for (let i = 0; i < n; i++) {
			const dx = b.x[i] - px0;
			const dy = b.y[i] - py0;
			const rmax = Math.max(b.wx[i], b.wy[i]) * 0.5;
			const ex = b.x[i] - b.px[i];
			const ey = b.y[i] - b.py[i];
			let sp = Math.sqrt(ex * ex + ey * ey);
			let travel;

			if (hasMove) {
				const mvx = b.vx[i];
				const mvy = b.vy[i];
				const ret = Math.hypot(b.ret_re[i], b.ret_im[i]);
				const attr = hasAttr && (b.attr_re[i] !== 0 || b.attr_im[i] !== 0);

				if (ret > 1.0001 || attr) {
					travel = Infinity; // 가속·인력이 커질 수 있어 거르지 않는다
				} else {
					const a = Math.hypot(b.ax[i], b.ay[i]);
					sp = Math.max(sp, Math.hypot(mvx, mvy));
					travel = sp * H + a * H * H * 0.5;
				}
			} else {
				travel = sp * H;
			}

			const d = Math.sqrt(dx * dx + dy * dy);

			if (d <= reach + travel + rmax + mMax + 2) {
				this.cand[nc] = i;
				this.candD[nc] = d;
				nc++;
			}
		}

		// 2단계: 너무 많으면 가까운 순으로 자른다(보수 동작 표시)
		let order = null;

		if (nc > cfg.max_relevant) {
			this.truncated = true;
			order = Array.from({ length: nc }, (_, k) => k);
			order.sort((p, q) => this.candD[p] - this.candD[q]);
			order.length = cfg.max_relevant;
		}

		// 3단계: 정밀 전개
		let nb = 0;
		const count = order ? order.length : nc;

		for (let k = 0; k < count; k++) {
			const i = this.cand[order ? order[k] : k];
			const j = nb;
			const base = j * W;
			const x = b.x[i];
			const y = b.y[i];
			const ex = x - b.px[i];
			const ey = y - b.py[i];

			// 모드 결정
			let mode = MODE_EXTRAP;
			let violated = false;
			const nomove = v.hasFlags && (b.flags[i] & 1) !== 0;

			if (hasMove && !nomove) {
				violated = this._violates(v, i, ex, ey);
				mode = this._classify(v.hasId ? b.id[i] : 0, v.hasId, violated, frame);
			}

			// 궤적 Q(0..H)
			this.trajX[base] = x;
			this.trajY[base] = y;

			if (mode === MODE_EXTRAP) {
				// 가장 최근에 실제로 본 이동으로 등속 외삽한다
				for (let t = 1; t <= H; t++) {
					this.trajX[base + t] = x + ex * t;
					this.trajY[base + t] = y + ey * t;
				}
			} else {
				this._fillExact(v, i, base);
			}

			// 크기·회전
			const wx = b.wx[i];
			const wy = b.wy[i];
			const circ = wx === wy;
			const ang = b.angle[i];
			this.bCirc[j] = circ ? 1 : 0;
			this.bRad[j] = wx * 0.5;
			this.bRmax[j] = Math.max(wx, wy) * 0.5;
			this.bRatio[j] = circ ? 1 : wx / wy;
			// 원본: cdir(-angle)을 곱한다
			this.bCos[j] = Math.cos(ang);
			this.bSin[j] = -Math.sin(ang);

			const mm = mode === MODE_EXACT ? cfg.margin.exact : mode === MODE_RECENT ? cfg.margin.recent : cfg.margin.extrap;
			this.bM0[j] = mm[0] * mscale;
			this.bK[j] = mm[1] * mscale;
			this.bMode[j] = mode;

			// 도달 가능한 시간 구간 [lo, hi]
			const rmax = this.bRmax[j];
			const rr = Math.max(1, this.bRatio[j]);
			let lo = 0;
			let hi = -1;

			for (let t = 1; t <= H; t++) {
				const m = (this.bM0[j] + this.bK[j] * t) * rr;
				const lim = vmax * t + rmax + m + 1;
				const lim2 = lim * lim;
				// 프레임 사이를 지나가는 빠른 탄을 놓치지 않도록 끝점이 아니라 이동 선분과의 거리를 쓴다
				const ax = this.trajX[base + t - 1] - px0;
				const ay = this.trajY[base + t - 1] - py0;
				const bx = this.trajX[base + t] - px0;
				const by = this.trajY[base + t] - py0;

				if (segOriginDist2(ax, ay, bx, by) <= lim2) {
					if (lo === 0) {
						lo = t;
					}
					hi = t;
				}
			}

			if (lo === 0) {
				continue; // 어느 시점에도 닿을 수 없다
			}

			this.bLo[j] = lo;
			this.bHi[j] = hi;
			nb++;
		}

		this.nb = nb;

		// 레이저 세그먼트
		this._buildLasers(v, reach);

		// 적
		let ne = 0;
		const en = v.enemies;

		for (let i = 0; i < en.n && ne < this.eX.length; i++) {
			const hr = en.hurt_radius[i];

			if (!(hr > 0)) {
				continue;
			}

			const d = Math.hypot(en.x[i] - px0, en.y[i] - py0);

			if (d <= reach + hr + cfg.margin.enemy[0] + cfg.margin.enemy[1] * H + 2) {
				this.eX[ne] = en.x[i];
				this.eY[ne] = en.y[i];
				this.eR[ne] = hr;
				ne++;
			}
		}

		this.ne = ne;
	}

	// 직전 한 걸음이 MoveParams 규칙과 맞는지(상태 없이 역산). 규칙으로 확인할 수 없으면 위반 아님.
	_violates(v, i, ex, ey) {
		const b = v.bullets;

		if (v.hasAge && b.age[i] < 1) {
			return false;
		}

		const rr = b.ret_re[i];
		const ri = b.ret_im[i];
		const den = rr * rr + ri * ri;

		if (den < 1e-9) {
			return false; // 속도가 매 프레임 가속도로 덮어씌워져 역산할 수 없다
		}

		// v_new = a + r·v_old (+ 인력) → v_old = (v_new − a − 인력) / r
		let nx = b.vx[i] - b.ax[i];
		let ny = b.vy[i] - b.ay[i];

		if (v.hasAttr && (b.attr_re[i] !== 0 || b.attr_im[i] !== 0)) {
			const avx = b.attr_x[i] - b.x[i];
			const avy = b.attr_y[i] - b.y[i];
			let mx = avx;
			let my = avy;
			const exp = b.attr_exp[i];

			if (exp !== 1) {
				const m2 = avx * avx + avy * avy;

				if (m2 === 0) {
					mx = 0;
					my = 0;
				} else {
					const m = Math.pow(m2, 0.5 * exp - 0.5);
					mx = avx * m;
					my = avy * m;
				}
			}

			nx -= b.attr_re[i] * mx - b.attr_im[i] * my;
			ny -= b.attr_re[i] * my + b.attr_im[i] * mx;
		}

		const ox = (nx * rr + ny * ri) / den;
		const oy = (ny * rr - nx * ri) / den;
		const err = Math.hypot(ex - ox, ey - oy);
		return err > this.cfg.trust.err_threshold;
	}

	// 원본 move_update를 H번 되풀이해 Q(1..H)를 채운다
	_fillExact(v, i, base) {
		const b = v.bullets;
		const H = this.H;
		let x = b.x[i];
		let y = b.y[i];
		let vx = b.vx[i];
		let vy = b.vy[i];
		const ax = b.ax[i];
		const ay = b.ay[i];
		const rr = b.ret_re[i];
		const ri = b.ret_im[i];
		const attr = v.hasAttr && (b.attr_re[i] !== 0 || b.attr_im[i] !== 0);
		const tr = attr ? b.attr_re[i] : 0;
		const ti = attr ? b.attr_im[i] : 0;
		const apx = attr ? b.attr_x[i] : 0;
		const apy = attr ? b.attr_y[i] : 0;
		const exp = attr ? b.attr_exp[i] : 1;

		for (let t = 1; t <= H; t++) {
			x += vx;
			y += vy;
			let nvx = ax + rr * vx - ri * vy;
			let nvy = ay + rr * vy + ri * vx;

			if (attr) {
				let avx = apx - x;
				let avy = apy - y;

				if (exp !== 1) {
					const m2 = avx * avx + avy * avy;

					if (m2 !== 0) {
						const m = Math.pow(m2, 0.5 * exp - 0.5);
						avx *= m;
						avy *= m;
					}
				}

				nvx += tr * avx - ti * avy;
				nvy += tr * avy + ti * avx;
			}

			vx = nvx;
			vy = nvy;
			this.trajX[base + t] = x;
			this.trajY[base + t] = y;
		}
	}

	// 충전 중인 레이저의 활성 시점을 폭의 변화로 추정한다.
	// 원본 laser_charge: 폭이 "충전 단계"에서 2 이하로 천천히 커지다가 "확장 단계"에서
	// 1.7 + 목표폭/20 × τ 로 직선 증가하고, 폭 > 목표폭 × 0.6 부터 충돌이 활성이다.
	// 확장 단계에서는 연속한 두 관측의 폭 차이(= 목표폭/20)로 목표폭과 남은 프레임을 구한다.
	// 충전 단계에서는 시작 시점을 알 수 없어 null(활성 시점 모름)을 돌려준다.
	_estimateActivation(key, width, frame) {
		const prev = this.laserWidth.get(key);
		this.laserWidth.set(key, { frame, width });

		if (!prev || prev.frame !== frame - 1 || !Number.isFinite(width)) {
			return null;
		}

		const slope = width - prev.width;

		if (width <= 2.0001 || slope < 0.25) {
			return null;
		}

		const target = slope * 20;
		const frames = Math.ceil((0.6 * target - width) / slope);
		return { act: Math.max(1, frames), targetRadius: Math.max(target * 0.5 - 4, 2) };
	}

	_buildLasers(v, reach) {
		const cfg = this.cfg;
		const P = v.player;
		const H = this.H;
		const segs = v.segs;
		const lasers = v.lasers;
		const mMax = (cfg.margin.laser[0] + cfg.margin.laser[1] * H) * this.mscale + cfg.margin.laser_unknown_extra;
		const hasAct = lasers.n > 0 && lasers.activate_in !== undefined && lasers.activate_in !== null;
		const hasId = lasers.n > 0 && lasers.id !== undefined && lasers.id !== null;
		const hasWidth = lasers.n > 0 && lasers.width !== undefined && lasers.width !== null;
		const next = new Map();
		const seen = new Set();
		let nl = 0;

		for (let li = 0; li < lasers.n; li++) {
			const key = hasId ? lasers.id[li] : li;
			const start = lasers.seg_start[li];
			const count = lasers.seg_count[li];
			const active = !!lasers.active[li];
			const prev = this.laserPrev.get(key);
			const rec = { n: count, ax: [], ay: [], bx: [], by: [] };

			for (let s = start; s < start + count; s++) {
				rec.ax.push(segs.ax[s]);
				rec.ay.push(segs.ay[s]);
				rec.bx.push(segs.bx[s]);
				rec.by.push(segs.by[s]);
			}

			next.set(key, rec);
			seen.add(key);

			// 충전 중이면 활성 시점을 알아낸다(관측에 직접 주어지면 그 값, 아니면 폭 이력으로 추정)
			let act = 0;
			let growth = 0;
			let unknownExtra = 0;

			if (!active) {
				const ai = hasAct ? lasers.activate_in[li] : NaN;
				const est = hasWidth ? this._estimateActivation(key, lasers.width[li], v.frame) : null;

				if (Number.isFinite(ai) && ai >= 0) {
					act = Math.max(1, Math.ceil(ai));
				} else if (est) {
					act = est.act;
					growth = est.targetRadius;
				} else {
					act = 1; // 활성 시점을 모르면 즉시 위험으로 본다
					unknownExtra = cfg.margin.laser_unknown_extra;
				}
			} else if (hasWidth) {
				this.laserWidth.set(key, { frame: v.frame, width: lasers.width[li] });
			}

			for (let s = start; s < start + count; s++) {
				if (nl >= cfg.max_laser_segs) {
					this.truncated = true;
					break;
				}

				const idx = s - start;
				let vax = 0, vay = 0, vbx = 0, vby = 0;
				let k = 0;
				let q = 0;

				// 직전 관측과 같은 레이저·같은 세그먼트 수일 때만 끝점 이동량으로 선형 이동을 추정한다
				if (prev && prev.n === count) {
					vax = segs.ax[s] - prev.ax[idx];
					vay = segs.ay[s] - prev.ay[idx];
					vbx = segs.bx[s] - prev.bx[idx];
					vby = segs.by[s] - prev.by[idx];
					q = 0.01 * Math.max(Math.hypot(vax, vay), Math.hypot(vbx, vby)); // 회전·곡선이면 시간 제곱으로 어긋난다
				} else {
					k = 0.3; // 이동을 알 수 없다
				}

				const sp = Math.max(Math.hypot(vax, vay), Math.hypot(vbx, vby));
				const trav = sp * H + q * H * H + k * H;
				const rmax = Math.max(segs.ra[s], segs.rb[s]) + mMax + trav + growth;
				const minx = Math.min(segs.ax[s], segs.bx[s]) - rmax;
				const maxx = Math.max(segs.ax[s], segs.bx[s]) + rmax;
				const miny = Math.min(segs.ay[s], segs.by[s]) - rmax;
				const maxy = Math.max(segs.ay[s], segs.by[s]) + rmax;

				if (maxx < P.x - reach || minx > P.x + reach || maxy < P.y - reach || miny > P.y + reach) {
					continue;
				}

				this.lAx[nl] = segs.ax[s];
				this.lAy[nl] = segs.ay[s];
				this.lBx[nl] = segs.bx[s];
				this.lBy[nl] = segs.by[s];
				this.lRa[nl] = segs.ra[s];
				this.lRb[nl] = segs.rb[s];
				this.lAct[nl] = act;
				// 활성이 된 뒤에는 폭이 목표까지 커지므로 반지름 증가분을 여유로 더한다
				this.lExtra[nl] = unknownExtra + (growth > 0 ? Math.max(0, growth - Math.max(segs.ra[s], segs.rb[s])) : 0);
				this.lVax[nl] = vax;
				this.lVay[nl] = vay;
				this.lVbx[nl] = vbx;
				this.lVby[nl] = vby;
				this.lK[nl] = k;
				this.lQ[nl] = q;
				nl++;
			}
		}

		// 사라진 레이저의 이력은 버린다
		for (const key of this.laserWidth.keys()) {
			if (!seen.has(key)) {
				this.laserWidth.delete(key);
			}
		}

		this.laserPrev = next;
		this.nl = nl;
	}

	// 시점 t에 플레이어가 (x0,y0)→(x1,y1)로 한 걸음 이동할 때의 피격 판정.
	// 반환: HIT_NONE / HIT_MARGIN / HIT_EXACT. cost가 true면 this.hz에 여유 비용을 더한다.
	stepEval(t, x0, y0, x1, y1, cost) {
		const H = this.H;
		const W = H + 1;
		const comfort = this.cfg.comfort;
		const vuln = t >= this.tVuln;
		let code = HIT_NONE;
		let hz = 0;
		const nb = this.nb;
		const trajX = this.trajX;
		const trajY = this.trajY;
		const slack = cost ? comfort : 0;

		for (let j = 0; j < nb; j++) {
			if (t < this.bLo[j] || t > this.bHi[j]) {
				continue;
			}

			const q0 = j * W + t - 1;
			let ax = x0 - trajX[q0];
			let ay = y0 - trajY[q0];
			let bx = x1 - trajX[q0 + 1];
			let by = y1 - trajY[q0 + 1];
			const ratio = this.bRatio[j];
			const m = (this.bM0[j] + this.bK[j] * t) * (ratio > 1 ? ratio : 1);
			const lim = this.bRmax[j] + m + slack;

			// 선분 경계 상자 대 탄 경계 정사각형
			if ((ax > lim && bx > lim) || (ax < -lim && bx < -lim) || (ay > lim && by > lim) || (ay < -lim && by < -lim)) {
				continue;
			}

			if (!this.bCirc[j]) {
				// 원본: 탄 좌표계에서 -angle만큼 돌리고 y를 x/y 비율만큼 늘려 지름 wx인 원으로 만든다
				const c = this.bCos[j];
				const s = this.bSin[j];
				const nax = ax * c - ay * s;
				const nay = (ax * s + ay * c) * ratio;
				const nbx = bx * c - by * s;
				const nby = (bx * s + by * c) * ratio;
				ax = nax;
				ay = nay;
				bx = nbx;
				by = nby;
			}

			const d2 = segOriginDist2(ax, ay, bx, by);
			const rad = this.bRad[j];

			if (vuln) {
				if (d2 <= rad * rad) {
					code = HIT_EXACT;
				} else if (code < HIT_MARGIN) {
					const r = rad + m;

					if (d2 <= r * r) {
						code = HIT_MARGIN;
					}
				}
			}

			if (cost) {
				const cb = Math.sqrt(d2) - rad;

				if (cb < comfort) {
					const q = (comfort - (cb < -comfort ? -comfort : cb)) / comfort;
					hz += q * q;
				}
			}
		}

		// 레이저: 시점 t의 형상 = 현재 형상 + 끝점 이동량 × t (선형 이동 가정)
		if (this.nl > 0) {
			const moved = x0 !== x1 || y0 !== y1;
			const mL = (this.cfg.margin.laser[0] + this.cfg.margin.laser[1] * t) * this.mscale;

			for (let s = 0; s < this.nl; s++) {
				if (t < this.lAct[s]) {
					continue;
				}

				const ax = this.lAx[s] + this.lVax[s] * t;
				const ay = this.lAy[s] + this.lVay[s] * t;
				const bx = this.lBx[s] + this.lVbx[s] * t;
				const by = this.lBy[s] + this.lVby[s] * t;
				const ra = this.lRa[s];
				const rb = this.lRb[s];
				const mS = mL + this.lExtra[s] + this.lK[s] * t + this.lQ[s] * t * t;
				const rm = (ra > rb ? ra : rb) + mS + slack;

				if (
					(x0 < ax - rm && x0 < bx - rm && x1 < ax - rm && x1 < bx - rm) ||
					(x0 > ax + rm && x0 > bx + rm && x1 > ax + rm && x1 > bx + rm) ||
					(y0 < ay - rm && y0 < by - rm && y1 < ay - rm && y1 < by - rm) ||
					(y0 > ay + rm && y0 > by + rm && y1 > ay + rm && y1 > by + rm)
				) {
					continue;
				}

				// 원본: 이동 선분이 레이저 중심선을 가로지르면 통과 방지로 피격
				if (vuln && moved && segSegIntersect(x0, y0, x1, y1, ax, ay, bx, by)) {
					code = HIT_EXACT;
				}

				const d = ucapsuleDist(x1, y1, ax, ay, bx, by, ra, rb);

				if (vuln) {
					if (d < 0) {
						code = HIT_EXACT;
					} else if (code < HIT_MARGIN && d < mS) {
						code = HIT_MARGIN;
					}
				}

				if (cost && d < comfort) {
					const q = (comfort - (d < -comfort ? -comfort : d)) / comfort;
					hz += q * q;
				}
			}
		}

		// 적 접촉: 원본은 거리 < hurt_radius(경계 미포함), 선분 판정 없음
		if (this.ne > 0) {
			const mE = this.cfg.margin.enemy[0] + this.cfg.margin.enemy[1] * t;

			for (let e = 0; e < this.ne; e++) {
				const d = Math.hypot(x1 - this.eX[e], y1 - this.eY[e]);
				const hr = this.eR[e];

				if (vuln) {
					if (d < hr) {
						code = HIT_EXACT;
					} else if (code < HIT_MARGIN && d < hr + mE) {
						code = HIT_MARGIN;
					}
				}

				if (cost && d - hr < comfort) {
					const q = (comfort - Math.max(d - hr, -comfort)) / comfort;
					hz += q * q;
				}
			}
		}

		if (cost) {
			this.hz += vuln ? hz : hz * 0.3;
		}

		return code;
	}
}
