// Codex 검토(PR #45, head 0ad6f88) 지적에 대한 회귀 테스트
//  P1: 이전 계획의 남은 이동이 0일 때 검증 경로(정지)와 반환 액션(이동)이 달랐다.
//  P2: MoveParams·인력 필드·탄 크기·퇴화 캡슐 등 수치 입력 검증이 부족했다.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as avoid from '../../ai/policies/avoid-v1/index.js';
import { Planner, candHoldBits, candDir } from '../../ai/policies/avoid-v1/planner.js';
import { Scene } from '../../ai/policies/avoid-v1/scene.js';
import { resolveConfig, HOLD } from '../../ai/policies/avoid-v1/config.js';
import { validateObs } from '../../ai/policies/avoid-v1/input.js';
import * as sc from './scenarios.js';
import { Sim } from './sim.js';
import { makeObs, buildScene, HIT_NONE } from './helpers.js';

const noClock = { now: () => 0 };

function plannerFor(obs, cfgOver) {
	const v = validateObs(obs);
	assert.ok(v.ok, v.reason);
	const cfg = resolveConfig(cfgOver);
	const scene = new Scene(cfg);
	scene.build(v, 1);
	const planner = new Planner(cfg, scene, noClock);
	planner.t0 = 0;
	return { v, cfg, scene, planner };
}

// ---- P1 ----------------------------------------------------------------------------------------

test('P1: 이전 계획의 남은 이동이 0이면 reuse는 정지 후보로 검증하고 정지를 돌려준다(Codex 재현)', () => {
	// 오른쪽 11px에 정지한 탄. 오른쪽 한 걸음(5.625)이면 닿는다.
	const obs = makeObs({ frame: 1, player: { x: 240, y: 480 }, bullets: [{ x: 251, y: 480, vx: 0, vy: 0, size: [12, 12] }] });
	const { v, planner } = plannerFor(obs, { horizon: 6, work_limit: 1 });
	planner.prev = 3; // 오른쪽
	planner.prevK = 0; // 남은 이동 0
	planner.planValid = true;
	const r = planner.decide(v);
	assert.equal(r.mode, 'reuse');
	assert.equal(r.c, 0, '반환 후보는 정지여야 한다');
	assert.equal(planner.chosenK(r.c), 0);
	assert.equal(candHoldBits(r.c, HOLD) & 0b1111, 0, '실제 입력에 이동 비트가 없다');
});

test('P1: 이동 후보의 롤아웃 k는 항상 1 이상이고 남은 이동은 1씩 줄다 0에서 정지로 넘어간다(prevK 1→0 경계)', () => {
	const obs = makeObs({ frame: 1, player: { x: 240, y: 480 } });
	const { v, planner } = plannerFor(obs, { horizon: 12 });
	planner.commit(3, 2);
	assert.equal(planner.prevK, 1);
	planner.commit(3, 1);
	assert.equal(planner.prevK, 0, '다음 단계는 정지');
	const r = planner.decide(v);
	assert.ok(r.c === 0 || planner.chosenK(r.c) >= 1, `이동 후보인데 k=0: c=${r.c} k=${planner.chosenK(r.c)}`);
});

test('P1: 예산이 끊긴 reuse에서도 검증 경로의 첫 걸음이 실제 입력과 같다', () => {
	// prevK=1(이동 한 걸음 남음)인 계획이 시간 초과 때 이어진다
	const obs = makeObs({ frame: 1, player: { x: 240, y: 480 }, bullets: [{ x: 300, y: 480, vx: 0, vy: 0, size: [12, 12] }] });
	const { v, planner } = plannerFor(obs, { horizon: 6, work_limit: 1 });
	planner.prev = 7; // 왼쪽
	planner.prevK = 1;
	planner.planValid = true;
	const r = planner.decide(v);
	assert.notEqual(r.c, -1);
	const W = 7;
	const bits = candHoldBits(r.c, HOLD);
	const dx = (bits & HOLD.RIGHT ? 1 : 0) - (bits & HOLD.LEFT ? 1 : 0);
	const x1 = planner.pathX[r.c * W + 1];
	assert.ok(Math.abs(x1 - (240 + dx * (bits & HOLD.FOCUS ? 2.5 : 5.625) * (bits & (HOLD.UP | HOLD.DOWN) ? Math.SQRT1_2 : 1))) < 1e-9);
});

test('P1: 모든 결정에서 검증 경로의 첫 걸음(meta.path1)이 시뮬레이터에서 실제로 일어난 위치와 같다', () => {
	for (const make of [() => sc.rain(1, { rate: 1.5 }), () => sc.crossing(2), () => sc.corner(3), () => sc.gapWall(4, { spacing: 16 }), () => sc.fastCross(5)]) {
		const policy = avoid.init({}, noClock);
		const sim = new Sim(make());
		let obs = sim.obs();
		let checked = 0;

		for (let i = 0; i < 500; i++) {
			const a = policy.decide(obs);
			sim.step(a.request ? 0 : a.hold);

			if (a.meta.path1) {
				assert.ok(Math.abs(sim.player.x - a.meta.path1[0]) < 1e-9 && Math.abs(sim.player.y - a.meta.path1[1]) < 1e-9,
					`${i}프레임: path1 ${a.meta.path1} 실제 ${sim.player.x},${sim.player.y} hold=${a.hold} mode=${a.meta.mode}`);
				checked++;
			}

			if (sim.hit) {
				break;
			}

			obs = sim.obs();
		}

		assert.ok(checked > 100);
	}
});

test('P1: 예산을 자주 끊어도(work_limit) 검증 경로와 입력이 어긋나지 않는다', () => {
	for (const limit of [1, 40, 300, 1500]) {
		const policy = avoid.init({ work_limit: limit }, noClock);
		const sim = new Sim(sc.gapWall(3, { spacing: 16 }));
		let obs = sim.obs();

		for (let i = 0; i < 400; i++) {
			const a = policy.decide(obs);
			sim.step(a.request ? 0 : a.hold);

			if (a.meta.path1 && !a.request) {
				assert.ok(Math.abs(sim.player.x - a.meta.path1[0]) < 1e-9 && Math.abs(sim.player.y - a.meta.path1[1]) < 1e-9,
					`limit ${limit} ${i}: ${a.meta.mode} path1 ${a.meta.path1} 실제 ${sim.player.x},${sim.player.y}`);
			}

			if (sim.hit) {
				break;
			}

			obs = sim.obs();
		}
	}
});

test('P1: rollout_stop_after는 1 이상 정수만 허용한다(0·음수·소수는 정지 롤아웃과 구분되지 않는다)', () => {
	for (const bad of [[0], [-1], [1.5], [4, 0], ['a']]) {
		assert.throws(() => avoid.init({ rollout_stop_after: bad }, noClock), /rollout_stop_after/, JSON.stringify(bad));
	}

	assert.doesNotThrow(() => avoid.init({ rollout_stop_after: [2, 5] }, noClock));
	assert.doesNotThrow(() => avoid.init({ rollout_stop_after: [] }, noClock));
	assert.deepEqual(avoid.init({ rollout_stop_after: [2, 5] }, noClock).describe().config.rollout_stop_after, [2, 5]);
});

// ---- P2 ----------------------------------------------------------------------------------------

function richObs() {
	// 정책이 읽는 모든 그룹에 값이 있는 관측
	return makeObs({
		frame: 50,
		boss: { present: 1, x: 240, y: 80 },
		bullets: [{ x: 200, y: 300, vx: 1, vy: 2, size: [12, 12] }, { x: 300, y: 250, vx: -1, vy: 2, size: [20, 8], angle: 0.3 }],
		lasers: [{ segs: [{ ax: 100, ay: 0, bx: 100, by: 500, wa: 20, wb: 20 }], active: true, width: 20 }],
		enemies: [{ x: 240, y: 100, hurt_radius: 7 }],
	});
}

// 정책이 읽는 필드와 그 그룹
const USED_FIELDS = {
	meta: ['frame'],
	player: ['x', 'y', 'speed_normal', 'speed_focus', 'bombs', 'deathtime', 'respawntime', 'recoverytime', 'bomb_endtime'],
	bullets: ['x', 'y', 'px', 'py', 'wx', 'wy', 'angle', 'vx', 'vy', 'ax', 'ay', 'ret_re', 'ret_im', 'attr_re', 'attr_im', 'attr_x', 'attr_y', 'attr_exp'],
	laser_segs: ['ax', 'ay', 'bx', 'by', 'ra', 'rb'],
	lasers: ['width'],
	enemies: ['x', 'y', 'hurt_radius'],
};

test('P2: 정책이 읽는 모든 수치 필드에 NaN·Infinity를 넣으면 observation_invalid로 중단하고 안전을 주장하지 않는다', () => {
	let cases = 0;

	for (const [group, keys] of Object.entries(USED_FIELDS)) {
		for (const key of keys) {
			for (const bad of [NaN, Infinity, -Infinity]) {
				const obs = richObs();
				const target = obs[group][key];

				if (Array.isArray(target)) {
					target[0] = bad;
				} else {
					obs[group][key] = bad;
				}

				const p = avoid.init({}, noClock);
				const a = p.decide(obs);
				assert.equal(a.meta.mode, 'halt', `${group}.${key}=${bad}`);
				assert.equal(a.request.reason, 'observation_invalid', `${group}.${key}=${bad}`);
				assert.equal(a.hold, 0);
				assert.equal(a.edges, 0);
				assert.equal(a.meta.safe_verified, false);
				cases++;
			}
		}
	}

	assert.ok(cases > 100);
});

test('P2: 인력 필드(attr_*)가 비유한이면 observation_invalid(Codex 지적)', () => {
	const obs = richObs();
	obs.bullets.attr_exp[1] = NaN;
	const a = avoid.init({}, noClock).decide(obs);
	assert.equal(a.request.reason, 'observation_invalid');
	assert.match(a.meta.detail, /attr_exp/);
});

test('P2: 음수 탄 지름은 observation_invalid, 0이면 위험 목록에서 빼고 보수 동작으로 표시한다', () => {
	const neg = richObs();
	neg.bullets.wx[0] = -3;
	assert.equal(avoid.init({}, noClock).decide(neg).request.reason, 'observation_invalid');

	const zero = makeObs({
		frame: 5,
		player: { x: 240, y: 480 },
		// 지름 0 탄이 플레이어 위치에 있다: 충돌 형상이 없으므로 위험 목록에서 빠진다
		bullets: [{ x: 240, y: 480, vx: 0, vy: 0, size: [0, 0] }, { x: 240, y: 440, vx: 0, vy: 6, size: [12, 12] }],
	});
	const a = avoid.init({}, noClock).decide(zero);
	assert.equal(a.request, null);
	assert.equal(a.meta.mode, 'conservative', '충돌 형상 없는 탄이 있으면 안전 판단을 주장하지 않는다');
	assert.equal(a.meta.safe_verified, false);
	assert.ok(a.hold & (HOLD.LEFT | HOLD.RIGHT | HOLD.UP | HOLD.DOWN), '진짜 위협은 여전히 피한다');
	const { sc: scene } = buildScene(zero, { horizon: 6 });
	assert.equal(scene.nb, 1);
});

test('P2: 퇴화 캡슐(길이 0 구간·반지름 차가 길이보다 큼)은 확정 피격으로 세지 않되(원본 NaN) 여유 판정은 보수 근사한다', () => {
	// 점 구간: a == b, 반지름 6
	const pt = makeObs({
		frame: 1, player: { x: 240, y: 480 },
		lasers: [{ segs: [{ ax: 244, ay: 480, bx: 244, by: 480, wa: 20, wb: 20 }], active: true, width: 20 }],
	});
	const { sc: scene } = buildScene(pt, { horizon: 6 });
	const code = scene.stepEval(1, 240, 480, 240, 480, false);
	assert.notEqual(code, 2, '원본은 NaN < 0 이 거짓이라 확정 피격이 아니다');
	assert.equal(code, 1, '그래도 여유 판정은 원 근사로 위험(4 < 6)으로 본다');

	const far = makeObs({
		frame: 1, player: { x: 240, y: 480 },
		lasers: [{ segs: [{ ax: 300, ay: 480, bx: 300, by: 480, wa: 20, wb: 20 }], active: true, width: 20 }],
	});
	const { sc: s2 } = buildScene(far, { horizon: 6 });
	assert.equal(s2.stepEval(1, 240, 480, 240, 480, false), HIT_NONE);

	// 반지름 차(10)가 구간 길이(2)보다 큰 경우
	const odd = makeObs({
		frame: 1, player: { x: 240, y: 480 },
		lasers: [{ segs: [{ ax: 244, ay: 480, bx: 246, by: 480, wa: 8, wb: 28 }], active: true, width: 20 }],
	});
	const { sc: s3 } = buildScene(odd, { horizon: 6 });
	const c3 = s3.stepEval(1, 240, 480, 240, 480, true);
	assert.notEqual(c3, 2);
	assert.ok(Number.isFinite(s3.hz));
});

test('P2: 전개 결과가 비유한이 되는 인력 탄은 외삽으로 대체하고 NaN이 비교를 오염시키지 않는다', () => {
	const obs = makeObs({ frame: 10, player: { x: 240, y: 480 }, bullets: [{ x: 240, y: 300, vx: 0, vy: 3, size: [12, 12] }] });
	// 지수가 매우 커서 pow가 Infinity가 되는 인력
	obs.bullets.attr_re[0] = 1e300;
	obs.bullets.attr_x[0] = 0;
	obs.bullets.attr_y[0] = 0;
	obs.bullets.attr_exp[0] = 50;
	const { sc: scene } = buildScene(obs, { horizon: 10 });
	assert.ok(scene.nonFinite >= 1);

	for (let j = 0; j < scene.nb; j++) {
		for (let t = 0; t <= 10; t++) {
			assert.ok(Number.isFinite(scene.trajX[j * 11 + t]) && Number.isFinite(scene.trajY[j * 11 + t]));
		}
	}

	const a = avoid.init({}, noClock).decide(obs);
	assert.equal(typeof a.hold, 'number');
	assert.ok(Number.isInteger(a.hold) && a.hold >= 0 && a.hold < 128);
});

test('P2: 퍼징 강화 — 정상 반환이면 hold는 유효한 비트이고, 안전 판단(safe_verified)은 유효한 관측에서만 나온다', () => {
	let seed = 7;
	const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
	const junk = [NaN, Infinity, -Infinity, undefined, null, 'x', -1, 1e9, 0.5, {}, []];
	let invalid = 0;

	for (let i = 0; i < 600; i++) {
		const obs = richObs();
		obs.meta.frame = 100 + i;
		const group = Object.keys(USED_FIELDS)[Math.floor(rnd() * 6)];
		const keys = USED_FIELDS[group];
		const key = keys[Math.floor(rnd() * keys.length)];
		const val = junk[Math.floor(rnd() * junk.length)];
		const target = obs[group][key];

		if (Array.isArray(target)) {
			target[Math.floor(rnd() * target.length)] = val;
		} else {
			obs[group][key] = val;
		}

		const wasValid = validateObs(obs).ok;
		const a = avoid.init({}, noClock).decide(obs);

		if (!wasValid) {
			invalid++;
			assert.equal(a.meta.mode, 'halt', `${group}.${key}=${String(val)}`);
			assert.equal(a.meta.safe_verified, false);
			assert.equal(a.hold, 0);
		} else {
			assert.ok(Number.isInteger(a.hold) && a.hold >= 0 && a.hold < 128);
		}
	}

	assert.ok(invalid > 300, `무효 관측 사례가 너무 적다: ${invalid}`);
});

// ---- 레이저 활성 시점 추정 휴리스틱 --------------------------------------------------------------

test('레이저 활성 시점 추정: 원본 충전 곡선에서 실제 활성 시점보다 늦게 추정하지 않는다(낙관 금지)', () => {
	const scn = sc.verticalLaser({ x: 240, charge: 70, dur: 220, target: 24 });
	const sim = new Sim(scn);
	const cfg = resolveConfig({ horizon: 30 });
	const scene = new Scene(cfg);
	// 실제 활성 시점
	let trueAct = -1;
	const probe = new Sim(sc.verticalLaser({ x: 240, charge: 70, dur: 220, target: 24 }));

	for (let f = 0; f < 120 && trueAct < 0; f++) {
		probe.frame = f;

		if (probe.laserActive(probe.lasers[0])) {
			trueAct = f;
		}
	}

	assert.ok(trueAct > 60);
	let engaged = 0;

	for (let f = 0; f <= trueAct - 1; f++) {
		sim.frame = f;
		const v = validateObs(sim.obs());
		scene.build(v, 1);
		const eng = scene.nl > 0 && scene.lExtra[0] < 6 && scene.lAct[0] > 1; // 폭 추정으로 얻은 활성 시점

		if (eng) {
			engaged++;
			assert.ok(f + scene.lAct[0] <= trueAct, `프레임 ${f}: 추정 활성 ${f + scene.lAct[0]} > 실제 ${trueAct}`);
		}
	}

	assert.ok(engaged >= 1, '확장 단계에서 추정이 한 번은 작동해야 한다');
});

test('레이저 활성 시점 추정: 폭이 직선으로 늘지 않거나 기울기가 흔들리면 추정하지 않고 즉시 위험으로 본다', () => {
	const cfg = resolveConfig({ horizon: 30 });
	const scene = new Scene(cfg);
	const mkv = (frame, width) => validateObs(makeObs({
		frame, player: { x: 240, y: 480 },
		lasers: [{ id: 1, segs: [{ ax: 240, ay: 0, bx: 240, by: 560, wa: width, wb: width }], active: false, width }],
	}));
	// 기울기가 일정하지 않은 폭(1.7 이후 5, 7, 12)
	for (const [f, w] of [[1, 3], [2, 5], [3, 6], [4, 12]]) {
		scene.build(mkv(f, w), 1);
	}

	assert.equal(scene.lAct[0], 1, '추정 불가 → 즉시 활성으로 본다');
	assert.ok(scene.lExtra[0] >= cfg.margin.laser_unknown_extra);
});
