// fixture 시나리오 검증. **합성 탄막(실제 게임 아님)**에서 회피 정책을 정지·단순 이동 기준선과 비교한다.
// 같은 시나리오·같은 시드에서 세 정책을 같은 조건으로 돌린다. 결과는 "fixture 결과"로만 보고한다.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as avoid from '../../ai/policies/avoid-v1/index.js';
import * as idle from '../../ai/policies/idle/index.js';
import * as simple from '../../ai/policies/simple-move/index.js';
import * as sc from './scenarios.js';
import { runEpisode, Sim, HOLD } from './sim.js';

const FRAMES = 900;
const SEEDS = [1, 2, 3];
const POLICIES = { idle, 'simple-move': simple, 'avoid-v1': avoid };

function runAll(name, make, extra = {}) {
	const out = {};

	for (const [pname, mod] of Object.entries(POLICIES)) {
		out[pname] = SEEDS.map(seed => {
			const scenario = Object.assign(make(seed), extra);
			const policy = mod.init({}, { now: () => performance.now() });
			const r = runEpisode({ policy, scenario, frames: FRAMES });
			return { seed, survived: r.survived, frames: r.survived_frames, hit: r.hit, released: r.released_frames, stats: policy.stats() };
		});
	}

	void name;
	return out;
}

function survivedAll(runs) {
	return runs.every(r => r.survived);
}

function meanFrames(runs) {
	return runs.reduce((a, r) => a + r.frames, 0) / runs.length;
}

const CASES = {
	'직선탄(비)': seed => sc.rain(seed),
	'교차탄': seed => sc.crossing(seed),
	'가속·감속·곡선 탄': seed => sc.accelerating(seed),
	'타원 탄': seed => sc.ellipses(seed),
	'고속탄(프레임 사이 통과)': seed => sc.fastCross(seed),
	'구석에서 시작(벽)': seed => sc.corner(seed),
	'좁은 틈 벽': seed => sc.gapWall(seed, { spacing: 16, size: 12 }),
};

for (const [label, make] of Object.entries(CASES)) {
	test(`fixture ${label}: 회피 정책은 ${FRAMES}프레임을 피격 없이 넘기고 기준선은 맞는다`, () => {
		const res = runAll(label, make);
		assert.ok(survivedAll(res['avoid-v1']), `avoid-v1 피격: ${JSON.stringify(res['avoid-v1'].filter(r => !r.survived).map(r => [r.seed, r.frames, r.hit]))}`);
		assert.ok(res.idle.some(r => !r.survived), 'idle이 한 번도 맞지 않으면 시나리오가 약하다');
		assert.ok(meanFrames(res['avoid-v1']) > meanFrames(res.idle), '평균 생존이 정지보다 길어야 한다');
		assert.ok(meanFrames(res['avoid-v1']) > meanFrames(res['simple-move']), '평균 생존이 단순 이동보다 길어야 한다');

		for (const r of res['avoid-v1']) {
			assert.equal(r.stats.halts.total, 0, `정상 관측에서는 입력 해제가 없어야 한다 (seed ${r.seed})`);
			assert.equal(r.stats.bombs.length, 0, '봄은 기본 꺼짐');
		}
	});
}

test('fixture 레이저(원본 충전 곡선): 활성 전에 레인을 벗어나 활성 구간 동안 피격 없음, 기준선은 맞는다', () => {
	const res = runAll('laser', () => sc.verticalLaser());
	assert.ok(survivedAll(res['avoid-v1']));
	assert.ok(res.idle.every(r => !r.survived && r.hit.by === 'laser'));
	assert.ok(res['simple-move'].every(r => !r.survived));

	// 활성 직전(프레임 68)에 이미 레이저 폭 밖에 있어야 한다
	const scenario = sc.verticalLaser();
	const policy = avoid.init({}, { now: () => 0 });
	const sim = new Sim(scenario);
	let obs = sim.obs();

	while (sim.frame < 68) {
		const a = policy.decide(obs);
		sim.step(a.hold);
		obs = sim.obs();
	}

	assert.ok(Math.abs(sim.player.x - 240) > 4, `활성 직전 위치 ${sim.player.x}`);
});

test('fixture 레이저(폭을 관측에서 알 수 없는 경우): 활성 시점을 모르므로 충전 중에도 위험으로 보고 피한다', () => {
	const res = runAll('laser-unknown', () => sc.verticalLaser({ hideWidth: true }));
	assert.ok(survivedAll(res['avoid-v1']));
});

test('fixture 이동 레이저(틈 있음): 끝점 이동을 선형 추정해 틈으로 들어간다', () => {
	const res = runAll('sweeping', () => sc.sweepingLaser());
	assert.ok(survivedAll(res['avoid-v1']), JSON.stringify(res['avoid-v1'].map(r => [r.frames, r.hit])));
	assert.ok(res.idle.every(r => !r.survived));
});

test('fixture MoveParams 없음: 직선 외삽 경로만으로도 정지 기준선을 넘는다', () => {
	for (const [label, make] of [['비', sc.rain], ['교차', sc.crossing], ['가속', sc.accelerating], ['틈 벽', s => sc.gapWall(s, { spacing: 16 })]]) {
		const res = runAll(label, make, { giveMove: false });
		assert.ok(survivedAll(res['avoid-v1']), `${label}: ${JSON.stringify(res['avoid-v1'].map(r => [r.frames, r.hit]))}`);
	}
});

test('fixture 캐릭터별 이동 속도: 속도 값을 관측에서 읽어 예측에 쓴다', () => {
	for (const player of [
		{ x: 240, y: 500, speedN: 5.625, speedF: 2.5 },   // 레이무
		{ x: 240, y: 500, speedN: 6.25, speedF: 2.75 },   // 마리사
		{ x: 240, y: 500, speedN: 6.0, speedF: 2.125 },   // 요무
	]) {
		const res = runAll('speed', s => sc.gapWall(s, { spacing: 16 }), { player });
		assert.ok(survivedAll(res['avoid-v1']), `speed ${player.speedN}: ${JSON.stringify(res['avoid-v1'].map(r => [r.frames, r.hit]))}`);
	}
});

test('이동 속도 예측: 롤아웃이 관측의 보통·저속 속도로 플레이어 위치를 전개한다', async () => {
	const { Planner, candHoldBits } = await import('../../ai/policies/avoid-v1/planner.js');
	const { Scene } = await import('../../ai/policies/avoid-v1/scene.js');
	const { resolveConfig } = await import('../../ai/policies/avoid-v1/config.js');
	const { validateObs } = await import('../../ai/policies/avoid-v1/input.js');
	const { makeObs } = await import('./helpers.js');
	void candHoldBits;

	// 오른쪽 11px 지점에 정지한 탄(반지름 6): 한 걸음 보통 속도(5.625)면 닿고 저속(2.5)이면 안 닿는다
	const obs = makeObs({ frame: 1, player: { x: 240, y: 480 }, bullets: [{ x: 251, y: 480, vx: 0, vy: 0, size: [12, 12] }] });
	const v = validateObs(obs);
	const cfg = resolveConfig({ horizon: 6 });
	const scene = new Scene(cfg);
	scene.build(v, 1);
	const planner = new Planner(cfg, scene, { now: () => 0 });
	// 후보 3 = 오른쪽 보통 속도, 후보 11 = 오른쪽 저속
	planner._rollout(3, 6, v.player.speed_normal, v.player);
	assert.equal(planner._sE, 1, '보통 속도 한 걸음(5.625)은 거리 5.375 < 6으로 닿는다');
	assert.equal(planner.tmpX[1], 240 + 5.625);
	planner._rollout(11, 6, v.player.speed_focus, v.player);
	assert.equal(planner.tmpX[1], 240 + 2.5);
	assert.ok(planner._sE > 1, '저속 첫 걸음(2.5)은 닿지 않는다(여러 걸음 뒤에는 닿는다)');
	planner._rollout(3, 6, 8, v.player);
	assert.equal(planner.tmpX[1], 248, '속도 값이 크면 더 멀리 전개한다');
	// 경계 고정
	const edge = makeObs({ frame: 1, player: { x: 462, y: 480 } });
	const ve = validateObs(edge);
	const sc2 = new Scene(cfg);
	sc2.build(ve, 1);
	const p2 = new Planner(cfg, sc2, { now: () => 0 });
	p2._rollout(3, 6, 5.625, ve.player);
	assert.equal(p2.tmpX[1], 464, '오른쪽 경계는 480 − 16에서 고정');
});

test('fixture 예측 실패: 규칙 밖에서 속도가 바뀌는 탄을 세고, 기준선보다 오래 산다', () => {
	const res = runAll('turning', s => sc.turning(s));
	const s = res['avoid-v1'];
	assert.ok(s.every(r => r.stats.pred_fail > 0), '예측 실패가 기록돼야 한다');
	assert.ok(meanFrames(s) > meanFrames(res.idle));
	assert.ok(survivedAll(s), JSON.stringify(s.map(r => [r.frames, r.hit])));
});

test('결정성: 같은 시드·같은 설정이면 에피소드 결과(위치 궤적)가 같다', () => {
	const run = () => {
		const policy = avoid.init({}, { now: () => 0 });
		const sim = new Sim(sc.crossing(2));
		let obs = sim.obs();
		const trail = [];

		for (let i = 0; i < 300; i++) {
			const a = policy.decide(obs);
			sim.step(a.request ? 0 : a.hold);
			trail.push(`${sim.player.x.toFixed(4)},${sim.player.y.toFixed(4)}`);
			obs = sim.obs();
		}

		return trail.join(';');
	};

	assert.equal(run(), run());
});

test('진동 억제: 위협이 없는 구간에서 방향이 계속 뒤집히지 않는다', () => {
	const policy = avoid.init({}, { now: () => 0 });
	const sim = new Sim(sc.gapWall(5, { spacing: 16, period: 48 }));
	let obs = sim.obs();
	let flips = 0;
	let prevDir = 0;
	let moves = 0;

	for (let i = 0; i < 600; i++) {
		const a = policy.decide(obs);
		const dir = (a.hold & HOLD.RIGHT ? 1 : 0) - (a.hold & HOLD.LEFT ? 1 : 0);

		if (dir !== 0) {
			moves++;

			if (prevDir !== 0 && dir !== prevDir) {
				flips++;
			}
			prevDir = dir;
		}

		sim.step(a.hold);
		obs = sim.obs();
	}

	assert.ok(sim.hit === null);
	assert.ok(flips <= moves * 0.2, `좌우 반전 ${flips} / 이동 입력 ${moves}`);
});

test('막다른 곳 회피: 구석에서 시작해도 구석에 머물지 않는다', () => {
	const policy = avoid.init({}, { now: () => 0 });
	const sim = new Sim(sc.corner(3));
	let obs = sim.obs();
	let cornerFrames = 0;

	for (let i = 0; i < 600; i++) {
		const a = policy.decide(obs);
		sim.step(a.hold);
		obs = sim.obs();

		if (sim.player.x < 60 && sim.player.y > 500) {
			cornerFrames++;
		}
	}

	assert.ok(sim.hit === null);
	assert.ok(cornerFrames < 200, `구석 체류 프레임 ${cornerFrames}/600`);
});

test('판단 시간: fixture 장면에서 p95가 프레임 예산(16.7 ms) 안이다(측정값은 기기마다 다르다)', () => {
	const policy = avoid.init({}, { now: () => performance.now() });
	const r = runEpisode({ policy, scenario: sc.rain(1, { rate: 1.5 }), frames: 600 });
	assert.ok(r.survived);
	assert.ok(r.decision_ms.p95 < 16.7, `p95 ${r.decision_ms.p95} ms`);
});
