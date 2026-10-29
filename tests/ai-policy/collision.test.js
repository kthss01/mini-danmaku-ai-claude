// 원본 판정 회귀 테스트(#21 v0.2 "원본 일치 경계 사례" 표 + 무작위 비교).
// 기준(oracle.js)은 원본 C 코드의 직역 포트이고, 비교 대상은 정책의 판정(Scene.stepEval의 확정 피격)이다.
// 원본 C를 직접 실행한 값이 아니라 직역 포트와의 비교이므로 문서에 그렇게 적는다.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mulberry32 } from './sim.js';
import { makeObs, buildScene, HIT_EXACT, HIT_NONE } from './helpers.js';
import {
	projectileHitsPlayer, laserHitsPlayer, enemyTouchesPlayer, ucapsuleDistFromPoint, linesegEllipseIntersect,
} from './oracle.js';
import { ucapsuleDist } from '../../ai/policies/avoid-v1/geometry.js';

// 정책 판정: 플레이어가 p0→p1로 한 걸음 움직일 때 t=1의 확정 피격 여부
function policyBulletHit(bullet, p0, p1, cfg) {
	const obs = makeObs({ player: { x: p0.x, y: p0.y }, bullets: [bullet] });
	const { sc } = buildScene(obs, { horizon: 6, ...cfg });
	return sc.nb === 1 && sc.stepEval(1, p0.x, p0.y, p1.x, p1.y, false) === HIT_EXACT;
}

function oracleBulletHit(b, p0, p1) {
	return projectileHitsPlayer(
		{ pos: { x: b.x + b.vx, y: b.y + b.vy }, prevpos: { x: b.x, y: b.y }, size: b.size, angle: (b.angle ?? 0) - Math.PI / 2 },
		p1, { x: p1.x - p0.x, y: p1.y - p0.y },
	);
}

test('경계 사례: 원형 탄은 d² ≤ (wx/2)²에서 피격(경계 포함)', () => {
	const b = { x: 100, y: 100, vx: 0, vy: 0, size: [12, 12] };
	const p = { x: 100 + 6, y: 100 };
	assert.equal(policyBulletHit(b, p, p), true, '거리 = 반지름(6)은 피격');
	assert.equal(policyBulletHit(b, { x: 106.0001, y: 100 }, { x: 106.0001, y: 100 }), false, '반지름 밖은 안전');
	assert.equal(policyBulletHit(b, { x: 100, y: 105.99 }, { x: 100, y: 105.99 }), true);
	assert.equal(oracleBulletHit(b, p, p), true);
});

test('경계 사례: collision_size는 지름이다(반지름으로 읽으면 틀린다)', () => {
	const b = { x: 100, y: 100, vx: 0, vy: 0, size: [20, 20] };
	// 지름 20 → 반지름 10. 거리 8은 피격, 거리 10.5는 안전
	assert.equal(policyBulletHit(b, { x: 108, y: 100 }, { x: 108, y: 100 }), true);
	assert.equal(policyBulletHit(b, { x: 110.5, y: 100 }, { x: 110.5, y: 100 }), false);
});

test('경계 사례: 타원 탄은 회전 후 y축을 늘려 같은 식을 쓴다', () => {
	// 관측 angle(= p->angle + π/2) = 0이면 x축이 wx(긴 축)이다
	const b = { x: 100, y: 100, vx: 0, vy: 0, size: [30, 10], angle: 0 };
	assert.equal(policyBulletHit(b, { x: 114, y: 100 }, { x: 114, y: 100 }), true, '긴 축 방향 14는 반지름 15 안');
	assert.equal(policyBulletHit(b, { x: 100, y: 106 }, { x: 100, y: 106 }), false, '짧은 축 방향 6은 반지름 5 밖');
	assert.equal(policyBulletHit(b, { x: 100, y: 104.9 }, { x: 100, y: 104.9 }), true);
	// 90도 돌리면 반대
	const c = { ...b, angle: Math.PI / 2 };
	assert.equal(policyBulletHit(c, { x: 100, y: 114 }, { x: 100, y: 114 }), true);
	assert.equal(policyBulletHit(c, { x: 106, y: 100 }, { x: 106, y: 100 }), false);
});

test('경계 사례: 판정 선분은 탄 기준 상대 이동이다(프레임 사이 통과도 피격)', () => {
	// 탄이 한 프레임에 40px 이동해 정지한 플레이어를 통과한다
	const b = { x: 60, y: 200, vx: 40, vy: 0, size: [8, 8] };
	const p = { x: 80, y: 200 };
	assert.equal(policyBulletHit(b, p, p), true, '터널링');
	assert.equal(oracleBulletHit(b, p, p), true);
	// 빗나가는 경우
	const q = { x: 80, y: 205 };
	assert.equal(policyBulletHit(b, q, q), false);
	// 플레이어가 이동하면서 정지한 탄과 엇갈린다
	const c = { x: 100, y: 100, vx: 0, vy: 0, size: [6, 6] };
	assert.equal(policyBulletHit(c, { x: 90, y: 100 }, { x: 110, y: 100 }), true, '플레이어가 탄을 가로지르며 이동');
});

test('무작위 비교: 탄 판정이 원본 직역 포트와 일치한다', () => {
	const rnd = mulberry32(12345);
	let hits = 0;
	const N = 40000;

	for (let i = 0; i < N; i++) {
		const circ = rnd() < 0.4;
		const w = 4 + rnd() * 36;
		const size = circ ? [w, w] : [w, 3 + rnd() * 30];
		const b = {
			x: 100 + (rnd() - 0.5) * 20, y: 100 + (rnd() - 0.5) * 20,
			vx: (rnd() - 0.5) * 30, vy: (rnd() - 0.5) * 30,
			size, angle: rnd() * 6.28318 - 3.14159,
		};
		const p0 = { x: 100 + (rnd() - 0.5) * 60, y: 100 + (rnd() - 0.5) * 60 };
		const stationary = rnd() < 0.3;
		const p1 = stationary ? p0 : { x: p0.x + (rnd() - 0.5) * 7.8, y: p0.y + (rnd() - 0.5) * 7.8 };
		const expect = oracleBulletHit(b, p0, p1);
		const got = policyBulletHit(b, p0, p1);

		if (expect) {
			hits++;
		}

		assert.equal(got, expect, `불일치 #${i}: ${JSON.stringify({ b, p0, p1 })}`);
	}

	assert.ok(hits > N * 0.05, `피격 사례가 너무 적다: ${hits}`);
});

test('ucapsule 거리: 원본 직역과 일치한다', () => {
	const rnd = mulberry32(777);

	for (let i = 0; i < 20000; i++) {
		const a = { x: rnd() * 200, y: rnd() * 200 };
		const b = { x: rnd() * 200, y: rnd() * 200 };
		const ra = 2 + rnd() * 10;
		const rb = ra + rnd() * 10; // 원본은 ra ≤ rb가 되도록 뒤집는다(laser.c)
		const p = { x: rnd() * 200, y: rnd() * 200 };
		const e = ucapsuleDistFromPoint(p, { a, b, ra, rb });
		const g = ucapsuleDist(p.x, p.y, a.x, a.y, b.x, b.y, ra, rb);
		if (Number.isNaN(e) && Number.isNaN(g)) {
			continue; // 반지름 차가 선분 길이보다 크면 원본도 NaN이고 NaN < 0은 거짓이다
		}

		assert.ok(Math.abs(e - g) < 1e-9, `${e} vs ${g}`);
	}
});

// 정책 판정(레이저): 활성 레이저 한 세그먼트
function policyLaserHit(seg, p0, p1) {
	const obs = makeObs({ player: { x: p0.x, y: p0.y }, lasers: [{ segs: [seg] }] });
	const { sc } = buildScene(obs, { horizon: 6 });
	return sc.stepEval(1, p0.x, p0.y, p1.x, p1.y, false) === HIT_EXACT;
}

function oracleLaserHit(seg, p0, p1) {
	return laserHitsPlayer([{ a: { x: seg.ax, y: seg.ay }, b: { x: seg.bx, y: seg.by }, wa: seg.wa, wb: seg.wb }], p1,
		{ x: p1.x - p0.x, y: p1.y - p0.y }, 1000);
}

test('경계 사례: 레이저는 캡슐 표면 거리 < 0에서만 피격(경계 미포함), 반지름 = max(폭/2 − 4, 2)', () => {
	// 폭 20 → 반지름 6. 세로 레이저 x=200
	const seg = { ax: 200, ay: 0, bx: 200, by: 400, wa: 20, wb: 20 };
	assert.equal(policyLaserHit(seg, { x: 205.9, y: 200 }, { x: 205.9, y: 200 }), true);
	assert.equal(policyLaserHit(seg, { x: 206, y: 200 }, { x: 206, y: 200 }), false, '표면 위(거리 0)는 피격이 아니다');
	assert.equal(policyLaserHit(seg, { x: 206.01, y: 200 }, { x: 206.01, y: 200 }), false);
	// 폭 4 → 반지름은 2(최소값)
	const thin = { ...seg, wa: 4, wb: 4 };
	assert.equal(policyLaserHit(thin, { x: 201.9, y: 200 }, { x: 201.9, y: 200 }), true);
	assert.equal(policyLaserHit(thin, { x: 202, y: 200 }, { x: 202, y: 200 }), false);
});

test('경계 사례: 이동 선분이 레이저 중심선을 가로지르면 끝점이 캡슐 밖이어도 피격', () => {
	const seg = { ax: 200, ay: 0, bx: 200, by: 400, wa: 4, wb: 4 }; // 반지름 2
	const p0 = { x: 197, y: 200 };
	const p1 = { x: 203, y: 200 };
	assert.equal(policyLaserHit(seg, p0, p1), true);
	assert.equal(oracleLaserHit(seg, p0, p1), true);
	// 가로지르지 않고 옆을 지나감
	assert.equal(policyLaserHit(seg, { x: 196, y: 200 }, { x: 197.5, y: 205 }), false);
	// 평행 이동은 교차로 보지 않는다(원본: d == 0이면 false)
	assert.equal(policyLaserHit(seg, { x: 197, y: 100 }, { x: 197, y: 150 }), false);
});

test('무작위 비교: 레이저 판정이 원본 직역 포트와 일치한다', () => {
	const rnd = mulberry32(2024);
	let hits = 0;
	const N = 30000;

	for (let i = 0; i < N; i++) {
		const wa = 4 + rnd() * 40;
		const wb = wa + rnd() * 20; // 원본은 width.a ≤ width.b가 되도록 뒤집는다
		const seg = {
			ax: 100 + (rnd() - 0.5) * 100, ay: 100 + (rnd() - 0.5) * 100,
			bx: 100 + (rnd() - 0.5) * 100, by: 100 + (rnd() - 0.5) * 100, wa, wb,
		};
		const p0 = { x: 100 + (rnd() - 0.5) * 7.80, y: 100 + (rnd() - 0.5) * 7.80 };
		const p1 = rnd() < 0.3 ? p0 : { x: p0.x + (rnd() - 0.5) * 7.8, y: p0.y + (rnd() - 0.5) * 7.8 };
		const e = oracleLaserHit(seg, p0, p1);
		const g = policyLaserHit(seg, p0, p1);

		if (e) {
			hits++;
		}

		assert.equal(g, e, `불일치 #${i}: ${JSON.stringify({ seg, p0, p1 })}`);
	}

	assert.ok(hits > N * 0.05, `피격 사례가 너무 적다: ${hits}`);
});

test('경계 사례: 적 접촉은 거리 < hurt_radius(경계 미포함), 선분 판정 없음', () => {
	function hit(enemy, p) {
		const obs = makeObs({ player: { x: p.x, y: p.y }, enemies: [enemy] });
		const { sc } = buildScene(obs, { horizon: 6 });
		return sc.stepEval(1, p.x, p.y, p.x, p.y, false) === HIT_EXACT;
	}

	assert.equal(hit({ x: 100, y: 100, hurt_radius: 7 }, { x: 106.99, y: 100 }), true);
	assert.equal(hit({ x: 100, y: 100, hurt_radius: 7 }, { x: 107, y: 100 }), false, '거리 = 반지름은 피격이 아니다');
	assert.equal(enemyTouchesPlayer({ x: 100, y: 100 }, 7, { x: 107, y: 100 }), false);
	assert.equal(hit({ x: 100, y: 100, hurt_radius: 0 }, { x: 100, y: 100 }), false, 'hurt_radius 0은 접촉 무해');

	// 선분 판정이 없다: 적 위를 가로질러 반대편에 멈추면 피격이 아니다
	const obs = makeObs({ player: { x: 80, y: 100 }, enemies: [{ x: 100, y: 100, hurt_radius: 7 }] });
	const { sc } = buildScene(obs, { horizon: 6 });
	assert.equal(sc.stepEval(1, 80, 100, 120, 100, false), HIT_NONE);
});

test('이동: 대각선도 같은 거리, 경계에서 16px 안쪽으로 고정(원본 player_move)', async () => {
	const { Planner } = await import('../../ai/policies/avoid-v1/planner.js');
	void Planner;
	const { Sim, HOLD } = await import('./sim.js');
	const sim = new Sim({ player: { x: 240, y: 280 } });
	sim.step(HOLD.RIGHT | HOLD.DOWN);
	const d = Math.hypot(sim.player.x - 240, sim.player.y - 280);
	assert.ok(Math.abs(d - 5.625) < 1e-9, `대각선 이동 거리 ${d}`);
	sim.step(HOLD.LEFT | HOLD.RIGHT); // 반대 키는 상쇄
	assert.equal(sim.player.vx, 0);
	const corner = new Sim({ player: { x: 17, y: 17 } });
	corner.step(HOLD.LEFT | HOLD.UP);
	assert.equal(corner.player.x, 16);
	assert.equal(corner.player.y, 16);
});

test('선분-타원 직역 포트 자체 점검: 원 경계(≤)와 bbox 사전 거름', () => {
	const seg = { a: { x: 10, y: 0 }, b: { x: 10, y: 0 } };
	assert.equal(linesegEllipseIntersect(seg, { x: 0, y: 0 }, [20, 20], 0), true);
	assert.equal(linesegEllipseIntersect({ a: { x: 10.001, y: 0 }, b: { x: 10.001, y: 0 } }, { x: 0, y: 0 }, [20, 20], 0), false);
});
