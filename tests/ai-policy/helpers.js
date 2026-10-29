// 테스트 공용 도구: 최소 관측 생성, 장면 구성, 가짜 시계
import { resolveConfig } from '../../ai/policies/avoid-v1/config.js';
import { validateObs } from '../../ai/policies/avoid-v1/input.js';
import { Scene, HIT_EXACT, HIT_MARGIN, HIT_NONE } from '../../ai/policies/avoid-v1/scene.js';

export { HIT_EXACT, HIT_MARGIN, HIT_NONE };

const BULLET_KEYS = ['x', 'y', 'px', 'py', 'wx', 'wy', 'angle', 'vx', 'vy', 'ax', 'ay', 'ret_re', 'ret_im',
	'attr_re', 'attr_im', 'attr_x', 'attr_y', 'attr_exp'];

const PHASE_NAMES = ['normal', 'hit_pending', 'dead', 'recovering', 'bombing'];

// bullets: [{x,y,vx,vy,size:[wx,wy],angle, ...}] — 이동 규칙이 맞도록 px,py를 역산해 채운다
// lasers: [{ segs:[{ax,ay,bx,by,wa,wb}], active, width, activate_in }]
// player.phase는 이름(문자열) 또는 정수 코드
export function makeObs({ frame = 100, player = {}, bullets = [], lasers = [], enemies = [], overflow = 0, boss } = {}) {
	const n = bullets.length;
	const b = { n, id: new Array(n), age: new Array(n).fill(10), flags: new Array(n).fill(0) };

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
		b.ret_re[i] = o.rr ?? 1;
		b.ret_im[i] = o.ri ?? 0;
		b.attr_exp[i] = 1;
		// 직전 이동은 규칙과 일치했다고 가정: v_old = v_new (a=0, r=1)
		b.px[i] = o.px ?? o.x - (o.vx ?? 0);
		b.py[i] = o.py ?? o.y - (o.vy ?? 0);
		b.wx[i] = (o.size || [12, 12])[0];
		b.wy[i] = (o.size || [12, 12])[1];
		b.angle[i] = o.angle ?? 0;
		b.flags[i] = o.nomove ? 1 : 0;
	});

	const segs = [];
	const lz = { n: lasers.length, id: [], active: [], width: [], seg_start: [], seg_count: [] };
	if (lasers.some(l => l.activate_in !== undefined)) {
		lz.activate_in = [];
	}
	lasers.forEach((l, li) => {
		lz.id.push(l.id ?? li + 1);
		lz.active.push(l.active === false ? 0 : 1);
		lz.width.push(l.width ?? l.segs[0].wa);
		lz.seg_start.push(segs.length);
		lz.seg_count.push(l.segs.length);

		if (lz.activate_in) {
			lz.activate_in.push(l.activate_in ?? 0);
		}

		for (const s of l.segs) {
			segs.push(s);
		}
	});
	const ls = {
		n: segs.length,
		ax: segs.map(s => s.ax), ay: segs.map(s => s.ay), bx: segs.map(s => s.bx), by: segs.map(s => s.by),
		ra: segs.map(s => Math.max(s.wa * 0.5 - 4, 2)), rb: segs.map(s => Math.max(s.wb * 0.5 - 4, 2)),
	};

	const pl = {
		x: 240, y: 480, vx: 0, vy: 0, speed_normal: 5.625, speed_focus: 2.5, bombs: 0, lives: 2, phase: 0,
		deathtime: -1, respawntime: 0, recoverytime: 0, bomb_endtime: 0, ...player,
	};

	if (typeof pl.phase === 'string') {
		pl.phase = PHASE_NAMES.indexOf(pl.phase);
	}

	return {
		meta: { schema_ver: 1, frame, episode_id: 1, overflow },
		player: pl,
		boss: boss || { present: 0, x: 0, y: 0 },
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
