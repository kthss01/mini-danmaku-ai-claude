// 테스트 공용 도구: 최소 관측 생성, 장면 구성, 가짜 시계
import { resolveConfig } from '../../ai/policies/avoid-v1/config.js';
import { validateObs } from '../../ai/policies/avoid-v1/input.js';
import { Scene, HIT_EXACT, HIT_MARGIN, HIT_NONE } from '../../ai/policies/avoid-v1/scene.js';

export { HIT_EXACT, HIT_MARGIN, HIT_NONE };

const BULLET_KEYS = ['x', 'y', 'px', 'py', 'wx', 'wy', 'angle', 'vx', 'vy', 'ax', 'ay', 'retention_re', 'retention_im',
	'attr_re', 'attr_im', 'attr_px', 'attr_py', 'attr_exp'];

// bullets: [{x,y,vx,vy,size:[wx,wy],angle, ...}] — 이동 규칙이 맞도록 px,py를 역산해 채운다
export function makeObs({ frame = 100, player = {}, bullets = [], lasers = [], enemies = [], overflow = 0, boss } = {}) {
	const n = bullets.length;
	const b = { n, id: new Array(n), age: new Array(n).fill(10), nomove: new Array(n).fill(0) };

	for (const k of BULLET_KEYS) {
		b[k] = new Array(n).fill(0);
	}

	bullets.forEach((o, i) => {
		b.id[i] = o.id ?? i + 1;
		b.x[i] = o.x;
		b.y[i] = o.y;
		b.vx[i] = o.vx ?? 0;
		b.vy[i] = o.vy ?? 0;
		b.ax[i] = o.ax ?? 0;
		b.ay[i] = o.ay ?? 0;
		b.retention_re[i] = o.rr ?? 1;
		b.retention_im[i] = o.ri ?? 0;
		b.attr_exp[i] = 1;
		// 직전 이동은 규칙과 일치했다고 가정: v_old = v_new (a=0, r=1)
		b.px[i] = o.px ?? o.x - (o.vx ?? 0);
		b.py[i] = o.py ?? o.y - (o.vy ?? 0);
		b.wx[i] = (o.size || [12, 12])[0];
		b.wy[i] = (o.size || [12, 12])[1];
		b.angle[i] = o.angle ?? 0;
		b.nomove[i] = o.nomove ? 1 : 0;
	});

	const segs = [];
	const lz = { n: lasers.length, id: [], active: [], activate_in: [] };
	lasers.forEach((l, li) => {
		lz.id.push(l.id ?? li + 1);
		lz.active.push(l.active === false ? 0 : 1);
		lz.activate_in.push(l.activate_in ?? 0);

		for (const s of l.segs) {
			segs.push({ li, ...s });
		}
	});
	const ls = {
		n: segs.length,
		laser: segs.map(s => s.li),
		ax: segs.map(s => s.ax), ay: segs.map(s => s.ay), bx: segs.map(s => s.bx), by: segs.map(s => s.by),
		ra: segs.map(s => Math.max(s.wa * 0.5 - 4, 2)), rb: segs.map(s => Math.max(s.wb * 0.5 - 4, 2)),
	};

	return {
		schema: 'taisei.ai.obs/0',
		frame,
		episode_id: 1,
		meta: { overflow },
		player: {
			x: 240, y: 480, vx: 0, vy: 0, speed_normal: 5.625, speed_focus: 2.5, bombs: 0, lives: 2, phase: 'normal',
			deathtime: -1, respawntime: 0, recoverytime: 0, bomb_endtime: 0, ...player,
		},
		boss,
		bullets: b,
		lasers: lz,
		laser_segs: ls,
		enemies: {
			n: enemies.length,
			id: enemies.map((_, i) => i + 1),
			x: enemies.map(e => e.x), y: enemies.map(e => e.y), hurt_radius: enemies.map(e => e.hurt_radius ?? 7),
		},
	};
}

export function buildScene(obs, cfg) {
	const v = validateObs(obs);

	if (!v.ok) {
		throw new Error(`관측이 유효하지 않다: ${v.reason} ${v.detail}`);
	}

	const config = resolveConfig(cfg);
	const sc = new Scene(config);
	sc.build(v, 1);
	return { sc, v, config };
}

// 호출할 때마다 step ms씩 흐르는 가짜 시계
export function fakeClock(step) {
	let t = 0;
	return { now: () => (t += step), reset: () => { t = 0; } };
}
