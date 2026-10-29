// 결정적 fixture 시뮬레이터. **실제 게임이 아니다.**
// 원본 한 프레임의 순서(입력 → 플레이어 이동 → 탄 이동 → 충돌 판정)와 판정식은 oracle.js(원본 직역)를 쓰고,
// 관측은 #21 v0.2 가정의 SoA 형식(`taisei.ai.obs/0`)으로 만든다. 계약 v1이 나오면 obsFrom()만 맞춘다.

import { moveUpdate, playerMove, projectileHitsPlayer, laserHitsPlayer, enemyTouchesPlayer } from './oracle.js';

export const HOLD = { UP: 1, DOWN: 2, LEFT: 4, RIGHT: 8, FOCUS: 16, SHOT: 32 };

export function mulberry32(seed) {
	let a = seed >>> 0;
	return function () {
		a = (a + 0x6D2B79F5) >>> 0;
		let t = a;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

const OUT = 120; // 화면 밖으로 이만큼 나가면 제거

export class Sim {
	// scn: { player:{x,y,speedN,speedF,bombs}, init(sim), spawn(sim, frame), startFrame }
	constructor(scn) {
		this.scn = scn;
		this.frame = scn.startFrame || 0;
		const p = scn.player || {};
		this.player = {
			x: p.x ?? 240, y: p.y ?? 496, vx: 0, vy: 0,
			speedN: p.speedN ?? 5.625, speedF: p.speedF ?? 2.5, bombs: p.bombs ?? 0, lives: 2,
		};
		this.bullets = [];
		this.lasers = [];
		this.enemies = [];
		this.nextId = 1;
		this.hit = null;
		this.f32 = scn.f32 !== false;
		this.giveActivateIn = scn.giveActivateIn !== false;
		this.giveMove = scn.giveMove !== false;
		this.overflow = 0;
		if (scn.init) {
			scn.init(this);
		}
	}

	// o: { x, y, v:[x,y], a, r, attr, ap, exp, size:[wx,wy], angle, nomove, task }
	addBullet(o) {
		const b = {
			id: this.nextId++,
			s: {
				x: o.x, y: o.y,
				v: { x: o.v ? o.v[0] : 0, y: o.v ? o.v[1] : 0 },
				a: { x: o.a ? o.a[0] : 0, y: o.a ? o.a[1] : 0 },
				r: { x: o.r ? o.r[0] : 1, y: o.r ? o.r[1] : 0 },
				attr: { x: o.attr ? o.attr[0] : 0, y: o.attr ? o.attr[1] : 0 },
				ap: { x: o.ap ? o.ap[0] : 0, y: o.ap ? o.ap[1] : 0 },
				exp: o.exp ?? 1,
			},
			px: o.x, py: o.y,
			size: o.size || [12, 12],
			angle: o.angle ?? 0,
			nomove: !!o.nomove,
			task: o.task || null,
			age: 0,
		};
		this.bullets.push(b);
		return b;
	}

	// o: { segs:[{a:{x,y}, b:{x,y}, wa, wb}] 또는 update(frame)→segs, activateAt, endAt, width }
	addLaser(o) {
		const l = { id: this.nextId++, ...o };
		this.lasers.push(l);
		return l;
	}

	addEnemy(o) {
		const e = { id: this.nextId++, hurt_radius: 7, ...o };
		this.enemies.push(e);
		return e;
	}

	laserSegs(l) {
		return l.update ? l.update(this.frame) : l.segs;
	}

	laserActive(l) {
		return this.frame >= l.activateAt && (l.endAt === undefined || this.frame < l.endAt);
	}

	step(hold) {
		this.frame++;
		const pl = this.player;

		// 입력 → 플레이어 이동 (반대 방향 키는 상쇄, 대각선은 정규화)
		const dx = (hold & HOLD.RIGHT ? 1 : 0) - (hold & HOLD.LEFT ? 1 : 0);
		const dy = (hold & HOLD.DOWN ? 1 : 0) - (hold & HOLD.UP ? 1 : 0);
		const len = Math.hypot(dx, dy);
		const speed = hold & HOLD.FOCUS ? pl.speedF : pl.speedN;
		let vel = { x: 0, y: 0 };

		if (len > 0) {
			const r = playerMove({ x: pl.x, y: pl.y }, { x: dx / len, y: dy / len }, speed);
			pl.x = r.pos.x;
			pl.y = r.pos.y;
			vel = r.vel;
		}

		pl.vx = vel.x;
		pl.vy = vel.y;

		// 패턴 태스크(탄 생성)
		if (this.scn.spawn) {
			this.scn.spawn(this, this.frame);
		}

		// 탄 이동 후 충돌
		for (const b of this.bullets) {
			b.px = b.s.x;
			b.py = b.s.y;

			if (!b.nomove) {
				moveUpdate(b.s);
			}

			if (b.task) {
				b.task(b, this.frame, this);
			}

			b.age++;

			if (this.hit === null && projectileHitsPlayer(
				{ pos: { x: b.s.x, y: b.s.y }, prevpos: { x: b.px, y: b.py }, size: b.size, angle: b.angle },
				{ x: pl.x, y: pl.y }, vel)) {
				this.hit = { frame: this.frame, by: 'bullet', id: b.id };
			}
		}

		// 레이저
		for (const l of this.lasers) {
			if (this.hit === null && this.laserActive(l) &&
				laserHitsPlayer(this.laserSegs(l), { x: pl.x, y: pl.y }, vel, l.bboxMargin ?? 30)) {
				this.hit = { frame: this.frame, by: 'laser', id: l.id };
			}
		}

		// 적 접촉
		for (const e of this.enemies) {
			if (e.task) {
				e.task(e, this.frame, this);
			}
			if (this.hit === null && enemyTouchesPlayer({ x: e.x, y: e.y }, e.hurt_radius, { x: pl.x, y: pl.y })) {
				this.hit = { frame: this.frame, by: 'enemy', id: e.id };
			}
		}

		this.bullets = this.bullets.filter(b => b.s.x > -OUT && b.s.x < 480 + OUT && b.s.y > -OUT && b.s.y < 560 + OUT);
	}

	obs() {
		const F = this.f32 ? Float32Array : Array;
		const mk = n => (this.f32 ? new Float32Array(n) : new Array(n).fill(0));
		const mkI = n => new Int32Array(n);
		const bs = this.bullets;
		const n = bs.length;
		const bullets = {
			n, id: mkI(n), x: mk(n), y: mk(n), px: mk(n), py: mk(n), wx: mk(n), wy: mk(n), angle: mk(n),
		};

		if (this.giveMove) {
			for (const k of ['vx', 'vy', 'ax', 'ay', 'retention_re', 'retention_im', 'attr_re', 'attr_im', 'attr_px', 'attr_py', 'attr_exp']) {
				bullets[k] = mk(n);
			}
			bullets.nomove = mkI(n);
			bullets.age = mkI(n);
		}

		for (let i = 0; i < n; i++) {
			const b = bs[i];
			bullets.id[i] = b.id;
			bullets.x[i] = b.s.x; bullets.y[i] = b.s.y;
			bullets.px[i] = b.px; bullets.py[i] = b.py;
			bullets.wx[i] = b.size[0]; bullets.wy[i] = b.size[1];
			bullets.angle[i] = b.angle + Math.PI / 2;

			if (this.giveMove) {
				bullets.vx[i] = b.s.v.x; bullets.vy[i] = b.s.v.y;
				bullets.ax[i] = b.s.a.x; bullets.ay[i] = b.s.a.y;
				bullets.retention_re[i] = b.s.r.x; bullets.retention_im[i] = b.s.r.y;
				bullets.attr_re[i] = b.s.attr.x; bullets.attr_im[i] = b.s.attr.y;
				bullets.attr_px[i] = b.s.ap.x; bullets.attr_py[i] = b.s.ap.y;
				bullets.attr_exp[i] = b.s.exp;
				bullets.nomove[i] = b.nomove ? 1 : 0;
				bullets.age[i] = b.age;
			}
		}

		const lasers = { n: this.lasers.length, id: mkI(this.lasers.length), active: mkI(this.lasers.length) };

		if (this.giveActivateIn) {
			lasers.activate_in = mk(this.lasers.length);
		}

		const segArr = [];

		this.lasers.forEach((l, li) => {
			lasers.id[li] = l.id;
			lasers.active[li] = this.laserActive(l) ? 1 : 0;

			if (this.giveActivateIn) {
				lasers.activate_in[li] = this.laserActive(l) ? 0 : Math.max(0, l.activateAt - this.frame);
			}

			for (const s of this.laserSegs(l)) {
				segArr.push({ li, s });
			}
		});

		const m = segArr.length;
		const laser_segs = { n: m, laser: mkI(m), ax: mk(m), ay: mk(m), bx: mk(m), by: mk(m), ra: mk(m), rb: mk(m) };
		segArr.forEach(({ li, s }, i) => {
			laser_segs.laser[i] = li;
			laser_segs.ax[i] = s.a.x; laser_segs.ay[i] = s.a.y;
			laser_segs.bx[i] = s.b.x; laser_segs.by[i] = s.b.y;
			laser_segs.ra[i] = Math.max(s.wa * 0.5 - 4, 2);
			laser_segs.rb[i] = Math.max(s.wb * 0.5 - 4, 2);
		});

		const en = { n: this.enemies.length, id: mkI(this.enemies.length), x: mk(this.enemies.length), y: mk(this.enemies.length), hurt_radius: mk(this.enemies.length) };
		this.enemies.forEach((e, i) => {
			en.id[i] = e.id; en.x[i] = e.x; en.y[i] = e.y; en.hurt_radius[i] = e.hurt_radius;
		});

		void F;
		const pl = this.player;
		return {
			schema: 'taisei.ai.obs/0',
			frame: this.frame,
			episode_id: 1,
			meta: { overflow: this.overflow },
			player: {
				x: pl.x, y: pl.y, vx: pl.vx, vy: pl.vy,
				speed_normal: pl.speedN, speed_focus: pl.speedF,
				bombs: pl.bombs, lives: pl.lives, phase: 'normal',
				deathtime: -1, respawntime: 0, recoverytime: 0, bomb_endtime: 0,
			},
			bullets, lasers, laser_segs, enemies: en,
		};
	}
}

// 한 에피소드를 돌린다. 정책이 request를 내면 그 프레임은 입력을 모두 해제한다.
export function runEpisode({ policy, scenario, frames, now }) {
	const sim = new Sim(scenario);
	const clock = now || (() => performance.now());
	let obs = sim.obs();
	let released = 0;
	let conservative = 0;
	let reuse = 0;
	const ms = [];
	let survived = 0;
	const hitsByPhase = [];

	for (let i = 0; i < frames; i++) {
		const t = clock();
		const a = policy.decide(obs);
		ms.push(clock() - t);
		let hold = a.hold;

		if (a.request) {
			released++;
			hold = 0;
		}
		if (a.meta && a.meta.mode === 'conservative') {
			conservative++;
		}
		if (a.meta && a.meta.mode === 'reuse') {
			reuse++;
		}

		sim.step(hold);

		if (sim.hit) {
			hitsByPhase.push(sim.hit);
			break;
		}

		survived++;
		obs = sim.obs();
	}

	ms.sort((x, y) => x - y);
	const pct = p => (ms.length ? ms[Math.min(ms.length - 1, Math.ceil(p * ms.length) - 1)] : 0);

	return {
		frames_requested: frames,
		survived_frames: survived,
		survived: sim.hit === null,
		hit: sim.hit,
		released_frames: released,
		conservative_frames: conservative,
		reuse_frames: reuse,
		decision_ms: { p50: pct(0.5), p95: pct(0.95), max: ms.length ? ms[ms.length - 1] : 0 },
		sim,
	};
}
