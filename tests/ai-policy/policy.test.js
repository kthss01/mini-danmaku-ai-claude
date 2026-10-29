// 정책 번들 계약 테스트(taisei.ai.policy/0): 형식, 오류 처리, 예산 초과 동작, 상태 초기화, 봄 기록
import test from 'node:test';
import assert from 'node:assert/strict';
import * as avoid from '../../ai/policies/avoid-v1/index.js';
import * as idle from '../../ai/policies/idle/index.js';
import * as simple from '../../ai/policies/simple-move/index.js';
import { makeObs, fakeClock } from './helpers.js';
import { HOLD } from './sim.js';

const noClock = { now: () => 0 };

function mk(cfg, host) {
	return avoid.init(cfg, host || noClock);
}

// 플레이어 바로 위에서 내려오는 탄 한 발(정지하면 몇 프레임 안에 맞는다)
function threatObs(frame = 100, extra = {}) {
	return makeObs({
		frame,
		player: { x: 240, y: 480 },
		bullets: [{ x: 240, y: 440, vx: 0, vy: 6, size: [12, 12] }],
		...extra,
	});
}

test('번들 형식: meta·init·정책 메서드를 내보낸다', () => {
	for (const m of [avoid, idle, simple]) {
		assert.equal(m.meta.schema, 'taisei.ai.policy/0');
		assert.equal(typeof m.meta.id, 'string');
		assert.equal(typeof m.init, 'function');
		const p = m.init({}, noClock);

		for (const f of ['decide', 'reset', 'dispose', 'stats', 'describe']) {
			assert.equal(typeof p[f], 'function', `${m.meta.id}.${f}`);
		}

		const a = p.decide(makeObs());
		assert.equal(typeof a.hold, 'number');
		assert.ok(a.bomb === 0 || a.bomb === 1);
		assert.equal(a.special, 0);
		assert.ok('request' in a && 'meta' in a);
	}

	assert.deepEqual(avoid.meta.obs_schema, ['taisei.ai.obs/0']);
	assert.equal(avoid.HOLD.SHOT, 32);
});

test('init: 잘못된 config는 예외, 알 수 없는 키도 거부', () => {
	assert.throws(() => avoid.init({ horizon: 2 }, noClock), /horizon/);
	assert.throws(() => avoid.init({ budget_ms: 0 }, noClock), /budget_ms/);
	assert.throws(() => avoid.init({ nope: 1 }, noClock), /알 수 없는 설정/);
	assert.throws(() => avoid.init({ weights: { clear: 'x' } }, noClock), /weights\.clear/);
	assert.throws(() => avoid.init({ on_frame_gap: 'x' }, noClock), /on_frame_gap/);
});

test('describe: 병합된 최종 설정을 돌려준다(params 해시 대상)', () => {
	const d = mk({ horizon: 20, weights: { pos: 0.1 } }).describe();
	assert.equal(d.id, 'avoid-v1');
	assert.equal(d.config.horizon, 20);
	assert.equal(d.config.weights.pos, 0.1);
	assert.equal(d.config.weights.clear, 1.0, '지정하지 않은 값은 기본값');
	assert.equal(d.config.bomb.enabled, false, '봄은 기본 꺼짐');
});

test('공격 유지: 매 프레임 SHOT 비트를 요청한다. shoot=false면 요청하지 않는다', () => {
	const a = mk().decide(makeObs());
	assert.ok(a.hold & HOLD.SHOT);
	const b = mk({ shoot: false }).decide(makeObs());
	assert.equal(b.hold & HOLD.SHOT, 0);
});

test('위협이 없으면 정지하고(진동 없음) 위협이 있으면 피한다', () => {
	const p = mk();
	const quiet = p.decide(makeObs({ frame: 1, player: { x: 240, y: 460 } }));
	assert.equal(quiet.hold & 0b1111, 0, '이동 입력 없음');
	assert.equal(quiet.meta.mode, 'normal');
	assert.equal(quiet.meta.safe_verified, true);

	const q = mk();
	const a = q.decide(threatObs(1));
	assert.ok(a.hold & (HOLD.LEFT | HOLD.RIGHT | HOLD.UP), `회피 이동이 있어야 한다: ${a.hold}`);
	assert.equal(a.meta.safe_verified, true);
	assert.equal(a.request, null);
});

test('관측 오류: 입력 해제(release) 요청으로 중단하고 던지지 않는다', () => {
	const bad = [
		undefined, null, 5, {},
		{ ...makeObs(), schema: 'taisei.ai.obs/9' },
		{ ...makeObs(), frame: -1 },
		{ ...makeObs(), frame: 1.5 },
		(() => { const o = makeObs(); o.player.x = NaN; return o; })(),
		(() => { const o = makeObs(); o.player.speed_normal = 0; return o; })(),
		(() => { const o = makeObs(); o.player.phase = 'weird'; return o; })(),
		(() => { const o = makeObs({ bullets: [{ x: 1, y: 1 }] }); o.bullets.x[0] = Infinity; return o; })(),
		(() => { const o = makeObs({ bullets: [{ x: 1, y: 1 }] }); delete o.bullets.wx; return o; })(),
		(() => { const o = makeObs(); o.bullets.n = -3; return o; })(),
		(() => { const o = makeObs(); o.player.x = 9999; return o; })(),
	];

	bad.forEach((obs, i) => {
		const p = mk();
		let a;
		assert.doesNotThrow(() => { a = p.decide(obs); }, `사례 ${i}`);
		assert.equal(a.hold, 0, `사례 ${i}: 입력 전부 해제`);
		assert.deepEqual(a.request && a.request.type, 'release');
		assert.equal(a.request.reason, 'observation_invalid');
		assert.equal(a.meta.mode, 'halt');
		assert.equal(a.meta.safe_verified, false, '중단은 안전을 주장하지 않는다');
		assert.ok(a.meta.detail, `사유 상세 ${i}`);
		assert.equal(p.stats().halts.by_reason.observation_invalid, 1);
	});
});

test('프레임 번호가 건너뛰면 halt(기본) 후 다음 프레임부터 재개한다', () => {
	const p = mk();
	assert.equal(p.decide(makeObs({ frame: 10 })).request, null);
	assert.equal(p.decide(makeObs({ frame: 11 })).request, null);
	const gap = p.decide(makeObs({ frame: 14 }));
	assert.equal(gap.request.reason, 'frame_gap');
	assert.equal(gap.hold, 0);
	assert.equal(p.decide(makeObs({ frame: 15 })).request, null, '다음 프레임은 정상 재개');

	const soft = mk({ on_frame_gap: 'reset' });
	soft.decide(makeObs({ frame: 10 }));
	assert.equal(soft.decide(makeObs({ frame: 14 })).request, null);
});

test('에피소드가 바뀌거나 프레임이 되감기면 내부 상태를 초기화하고 이어간다', () => {
	const p = mk();

	for (let f = 1; f <= 5; f++) {
		p.decide(threatObs(f));
	}

	const o = threatObs(1);
	o.episode_id = 2;
	const a = p.decide(o);
	assert.equal(a.request, null);
	const rewound = p.decide(threatObs(1, {}));
	assert.equal(rewound.request, null, '같은 프레임 반복도 던지지 않는다');
});

test('결정성: 같은 관측열과 초기 상태이면 같은 출력', () => {
	const run = () => {
		const p = mk();
		const out = [];

		for (let f = 1; f <= 40; f++) {
			const x = 240 + 30 * Math.sin(f / 5);
			const a = p.decide(makeObs({
				frame: f, player: { x: 240, y: 480 },
				bullets: [{ x, y: 380 + f, vx: 0, vy: 4, size: [12, 12] }, { x: 200, y: 300 + 3 * f, vx: 0.5, vy: 3, size: [10, 10] }],
			}));
			out.push([a.hold, a.bomb, a.meta.mode, a.meta.choice, a.meta.s_exact, a.meta.s_margin].join(','));
		}

		return out;
	};

	assert.deepEqual(run(), run());
});

test('overflow가 있으면 보수 동작(conservative)으로 표시하고 안전 판단을 주장하지 않는다', () => {
	const p = mk();
	const a = p.decide(threatObs(1, { overflow: 1 }));
	assert.equal(a.meta.mode, 'conservative');
	assert.equal(a.meta.safe_verified, false);
	assert.equal(a.request, null, '입력은 계속한다(중단이 아님)');
	assert.equal(p.stats().conservative_frames, 1);
});

test('사망 처리 중(dead)·데스봄 유예(hit_pending)에는 회피 계산을 쉬고 공격만 유지', () => {
	const p = mk();
	const dead = p.decide(makeObs({ frame: 1, player: { phase: 'dead', x: -100, y: -100 } }));
	assert.equal(dead.meta.mode, 'dead_wait');
	assert.equal(dead.hold, HOLD.SHOT);
	assert.equal(dead.request, null);
	const pend = p.decide(threatObs(2, { player: { phase: 'hit_pending', bombs: 2 } }));
	assert.equal(pend.meta.mode, 'dead_wait');
	assert.equal(pend.bomb, 0, '데스봄은 기본 꺼짐');
});

test('데스봄 옵션: hit_pending에서 봄을 한 번 쓰고 기록한다', () => {
	const p = mk({ bomb: { enabled: true, deathbomb: true } });
	const a = p.decide(threatObs(1, { player: { phase: 'hit_pending', bombs: 2 } }));
	assert.equal(a.bomb, 1);
	const b = p.decide(threatObs(2, { player: { phase: 'hit_pending', bombs: 2 } }));
	assert.equal(b.bomb, 0, '에피소드당 최대 횟수 제한');
	const s = p.stats();
	assert.equal(s.bombs.length, 1);
	assert.equal(s.bombs[0].kind, 'deathbomb');
});

// 모든 방향이 막힌 상황: 플레이어 둘레에서 안쪽으로 모이는 탄 고리
function ringObs(frame, extra = {}) {
	const bullets = [];

	for (let k = 0; k < 28; k++) {
		const a = (k / 28) * Math.PI * 2;
		bullets.push({ x: 240 + Math.cos(a) * 34, y: 300 + Math.sin(a) * 34, vx: -Math.cos(a) * 4, vy: -Math.sin(a) * 4, size: [14, 14] });
	}

	return makeObs({ frame, player: { x: 240, y: 300, bombs: 2 }, bullets, ...extra });
}

test('봄: 기본은 쓰지 않고, 켜면 확정 피격이 임박할 때 한 번 쓰고 기록한다', () => {
	const off = mk();
	const a = off.decide(ringObs(1));
	assert.equal(a.meta.plan_mode, 'doomed');
	assert.equal(a.bomb, 0);
	assert.equal(off.stats().bombs.length, 0);

	const on = mk({ bomb: { enabled: true } });
	const b = on.decide(ringObs(1));
	assert.equal(b.bomb, 1);
	const rec = on.stats().bombs[0];
	assert.equal(rec.kind, 'policy');
	assert.equal(rec.frame, 1);
	assert.ok(rec.predicted_hit_frame >= 1 && rec.predicted_hit_frame <= 9);
	// 봄이 없으면 쓰지 않는다
	const none = mk({ bomb: { enabled: true } });
	assert.equal(none.decide(ringObs(1, { player: { bombs: 0 } })).bomb, 0);
});

test('무적 구간(recovering)의 피격은 점수에 넣지 않고, 종료 뒤의 피격만 본다', () => {
	const p = mk({ horizon: 30 });
	// 5프레임 뒤에 맞을 탄이지만 프레임 100 + 60까지 무적
	const a = p.decide(threatObs(100, { player: { phase: 'recovering', recoverytime: 160 } }));
	assert.equal(a.meta.mode, 'normal');
	assert.equal(a.meta.s_exact, 31, '무적 중에는 확정 피격이 없다');
	// 무적이 곧 끝나면 피한다
	const q = mk({ horizon: 30 });
	const b = q.decide(threatObs(100, { player: { phase: 'recovering', recoverytime: 103 } }));
	assert.ok(b.hold & (HOLD.LEFT | HOLD.RIGHT | HOLD.UP));
});

test('예산 초과(1): ①을 끝낸 안전 후보가 있으면 그중에서 고르고 확인 안 된 후보는 고르지 않는다', () => {
	const clk = fakeClock(100); // 시계 호출마다 100ms → 첫 확인 직후 예산 초과
	const p = mk({}, clk);
	const a = p.decide(makeObs({ frame: 1 }));
	assert.equal(a.request, null);
	assert.equal(a.meta.over_budget, true);
	assert.equal(a.meta.safe_verified, true, '정지 후보의 ①은 끝났다');
	assert.equal(a.meta.complete, false, '비용 계산은 끝나지 않았다');
	assert.equal(a.hold & 0b1111, 0);
});

test('예산 초과(2): 안전 후보가 확인되기 전에 끊기면 입력 해제(halt)이며 안전을 주장하지 않는다', () => {
	const clk = fakeClock(100);
	const p = mk({}, clk);
	// 정지가 먼저 평가되는데 정지는 맞는다 → 안전 후보 없음
	const a = p.decide(threatObs(1));
	assert.equal(a.meta.mode, 'halt');
	assert.equal(a.request.type, 'release');
	assert.equal(a.request.reason, 'policy_deadline');
	assert.equal(a.hold, 0);
	assert.equal(a.meta.safe_verified, false);
	const s = p.stats();
	assert.equal(s.halts.by_reason.policy_deadline, 1);
});

test('예산 초과(3): 이전 계획의 다음 단계가 현재 관측에서도 안전하면 그것을 이어간다(reuse)', () => {
	let slow = false;
	let t = 0;
	const clk = { now: () => (t += slow ? 100 : 0.001) };
	const p = mk({}, clk);
	// 정상 프레임: 위협을 피하는 계획을 세운다
	const first = p.decide(threatObs(1));
	assert.equal(first.request, null);
	slow = true;
	const second = p.decide(threatObs(2));
	assert.equal(second.request, null);
	assert.equal(second.meta.over_budget, true);
	assert.equal(second.meta.mode, 'reuse');
	assert.equal(second.meta.safe_verified, true);
	assert.equal(second.hold, first.hold, '이전 계획을 그대로 이어간다');
});

test('예산 초과 연속: 설정 횟수를 넘으면 suspend 요청(policy_deadline)', () => {
	const clk = fakeClock(100);
	const p = mk({ deadline_suspend_after: 3 }, clk);
	const types = [];

	for (let f = 1; f <= 4; f++) {
		types.push(p.decide(threatObs(f)).request.type);
	}

	assert.deepEqual(types, ['release', 'release', 'suspend', 'suspend']);
	assert.equal(p.stats().suspend_requests, 2);
});

test('작업량 상한(work_limit)으로 시계 없이도 예산 초과를 결정적으로 재현한다', () => {
	const p = mk({ work_limit: 1 });
	const a = p.decide(threatObs(1));
	assert.equal(a.meta.mode, 'halt');
	assert.equal(a.request.reason, 'policy_deadline');
});

test('dispose 이후 decide는 halt', () => {
	const p = mk();
	p.dispose();
	const a = p.decide(makeObs());
	assert.equal(a.request.type, 'release');
	assert.equal(a.request.reason, 'disposed');
});

test('stats: 판단 시간 분포·모드 횟수를 직렬화 가능한 값으로 돌려준다', () => {
	const clk = fakeClock(0.01);
	const p = mk({}, clk);

	for (let f = 1; f <= 5; f++) {
		p.decide(makeObs({ frame: f }));
	}

	const s = JSON.parse(JSON.stringify(p.stats()));
	assert.equal(s.decisions, 5);
	assert.equal(s.modes.normal, 5);
	assert.equal(s.decision_ms.n, 5);
	assert.ok(s.decision_ms.p50 > 0 && s.decision_ms.max >= s.decision_ms.p95);
	assert.equal(s.halts.total, 0);
});

test('trace: 최근 N프레임의 결정 요약을 보관한다', () => {
	const p = mk({ trace: 3 });

	for (let f = 1; f <= 6; f++) {
		p.decide(makeObs({ frame: f }));
	}

	const t = p.trace();
	assert.equal(t.length, 3);
	assert.deepEqual(t.map(x => x.frame), [4, 5, 6]);
});

test('퍼징: 무작위로 망가진 관측에도 예외를 던지지 않는다', () => {
	const p = mk();
	let seed = 99;
	const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
	const junk = [NaN, Infinity, -Infinity, undefined, null, 'x', -1, 1e9, 0.5];

	for (let i = 0; i < 300; i++) {
		const o = makeObs({ frame: i + 1, bullets: [{ x: 240, y: 300, vy: 3 }, { x: 100, y: 100, vx: 1 }] });
		const keys = ['player', 'bullets', 'lasers', 'laser_segs', 'enemies', 'meta'];
		const k = keys[Math.floor(rnd() * keys.length)];
		const target = o[k];

		if (target && typeof target === 'object') {
			const subs = Object.keys(target);
			const sk = subs[Math.floor(rnd() * subs.length)];
			target[sk] = junk[Math.floor(rnd() * junk.length)];
		}

		assert.doesNotThrow(() => {
			const a = p.decide(o);
			assert.equal(typeof a.hold, 'number');
		}, `사례 ${i} (${k})`);
	}
});
