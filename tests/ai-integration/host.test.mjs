// AI 호스트(web/game/ai-host.js) 단위 검증. mock 어댑터를 쓰므로 "mock 성공"이며 실제 게임 결과가 아니다.
// 실행: node --test tests/ai-integration/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { createHost, REASON_INFO } = require('../../web/game/ai-host.js');
const { createMockAdapter, createSweepPolicy, HOLD } = require('./mock-adapter.js');

function setup({ policy = true, kind = 'mock', adapterOptions } = {}) {
	const host = createHost();
	const adapter = createMockAdapter(adapterOptions);
	host.attach(adapter, kind);
	if (policy) host.setPolicy(createSweepPolicy());
	return { host, adapter, sim: adapter.sim };
}

test('어댑터가 없으면 unavailable이고 상태는 manual이다', () => {
	const host = createHost();
	assert.equal(host.enable(), 'unavailable');
	assert.equal(host.resume(), 'unavailable');
	assert.equal(host.suspend(), 'unavailable');
	assert.equal(host.disable(), 'unavailable');
	const s = host.state();
	assert.equal(s.available, false);
	assert.equal(s.mode, 'manual');
	assert.ok(s.unavailableReason);
});

test('정책 없이 enable하면 no_policy이고 소유권은 바뀌지 않는다', () => {
	const { host } = setup({ policy: false });
	assert.equal(host.enable(), 'no_policy');
	assert.equal(host.state().mode, 'manual');
});

test('enable → ai_active, 프레임마다 정책 액션이 다음 프레임에 적용된다', () => {
	const { host, sim } = setup();
	assert.equal(host.enable(), 'ok');
	assert.equal(host.state().mode, 'ai_active');
	sim.tick(3);
	const c = sim.counters();
	assert.equal(c.applied, 2); // 첫 틱은 아직 액션이 없다(첫 관측은 틱 1 뒤)
	assert.equal(c.missing, 1);
	assert.equal(c.stale + c.dup, 0);
	const log = sim.appliedLog().filter((e) => e.source === 'ai' && !e.missing);
	assert.ok(log.every((e) => (e.hold & HOLD.SHOT) !== 0 && (e.hold & HOLD.LEFT) !== 0));
	assert.ok(host.decisionStats().count >= 3);
});

test('스테이지 밖에서 enable하면 ai_suspended(not_playing)가 된다', () => {
	const { host, sim } = setup({ adapterOptions: { inStage: false } });
	assert.equal(host.enable(), 'not_playing');
	const s = host.state();
	assert.equal(s.mode, 'ai_suspended');
	assert.equal(s.reason, 'not_playing');
	sim.enterStage();
	assert.equal(host.resume(), 'ok');
	assert.equal(host.state().mode, 'ai_active');
});

test('사용자 키 입력은 즉시 manual로 바꾸고 입력을 섞지 않는다', () => {
	const { host, sim } = setup();
	host.enable();
	sim.tick(2);
	sim.userKey();
	const s = host.state();
	assert.equal(s.mode, 'manual');
	assert.equal(s.reason, 'user_input');
	assert.equal(sim.hasPendingSlot(), false);
	sim.setPhysicalHold(HOLD.UP);
	sim.tick(1);
	const last = sim.appliedLog().pop();
	assert.equal(last.source, 'physical');
	assert.equal(last.hold, HOLD.UP);
});

test('포커스 상실은 ai_suspended(focus_lost)이고 돌아와도 자동 재개하지 않는다', () => {
	const { host, sim } = setup();
	host.enable();
	sim.tick(2);
	assert.equal(host.notifyFocusLost(), 'ok');
	let s = host.state();
	assert.equal(s.mode, 'ai_suspended');
	assert.equal(s.reason, 'focus_lost');
	assert.equal(sim.hasPendingSlot(), false); // 대기 슬롯 폐기
	sim.tick(5);
	s = host.state();
	assert.equal(s.mode, 'ai_suspended'); // 자동 재개 없음
	assert.equal(host.resume(), 'ok');
	assert.equal(host.state().mode, 'ai_active');
});

test('포커스 상실 알림은 ai_active가 아니면 아무것도 하지 않는다', () => {
	const { host } = setup();
	assert.equal(host.notifyFocusLost(), 'noop');
	assert.equal(host.state().mode, 'manual');
});

test('일시정지는 ai_suspended(pause)이고 일시정지 중 resume은 not_playing으로 유지된다', () => {
	const { host, sim } = setup();
	host.enable();
	sim.setPaused(true);
	assert.equal(host.state().reason, 'pause');
	assert.equal(host.resume(), 'not_playing');
	assert.equal(host.state().mode, 'ai_suspended');
	sim.setPaused(false);
	assert.equal(host.state().mode, 'ai_suspended'); // 풀려도 유지
	assert.equal(host.resume(), 'ok');
	assert.equal(host.state().mode, 'ai_active');
});

test('게임 오버·스테이지 종료·재시작도 ai_suspended이고 사유 문자열이 계약과 같다', () => {
	for (const [method, reason] of [['gameOver', 'game_over'], ['stageEnd', 'stage_end'], ['restart', 'restart']]) {
		const { host, sim } = setup();
		host.enable();
		sim[method]();
		const s = host.state();
		assert.equal(s.mode, 'ai_suspended', method);
		assert.equal(s.reason, reason, method);
		assert.ok(REASON_INFO[reason], reason);
	}
});

test('정책이 예외를 던지면 manual(policy_error)로 바뀌고 오류가 남는다', () => {
	const { host, sim } = setup({ policy: false });
	host.setPolicy({ decide() { throw new Error('boom'); } }, { id: 'broken' });
	const events = [];
	host.onEvent((e) => events.push(e));
	host.enable();
	sim.tick(2);
	const s = host.state();
	assert.equal(s.mode, 'manual');
	assert.equal(s.reason, 'policy_error');
	assert.match(s.lastError.message, /boom/);
	assert.ok(events.some((e) => e.type === 'error' && e.code === 'policy_error'));
	assert.ok(events.some((e) => e.type === 'transition' && e.state === 'manual'));
});

test('정책이 올바르지 않은 액션을 돌려주면 policy_error', () => {
	const { host, sim } = setup({ policy: false });
	host.setPolicy({ decide() { return null; } }, { id: 'null-policy' });
	host.enable();
	sim.tick(2);
	assert.equal(host.state().reason, 'policy_error');
});

test('request.release는 hold 0을 제출하고 소유권은 유지한다', () => {
	const { host, sim } = setup({ policy: false });
	host.setPolicy({ decide: () => ({ hold: HOLD.LEFT, request: { type: 'release', reason: 'observation_invalid' } }) });
	host.enable();
	sim.tick(3);
	assert.equal(host.state().mode, 'ai_active');
	const ai = sim.appliedLog().filter((e) => e.source === 'ai' && !e.missing);
	assert.ok(ai.length >= 1 && ai.every((e) => e.hold === 0));
	assert.ok(host.decisionStats().releases >= 1);
});

test('request.suspend는 ai_suspended(허용 사유)로 올린다', () => {
	const { host, sim } = setup({ policy: false });
	host.setPolicy({ decide: () => ({ hold: 0, request: { type: 'suspend', reason: 'policy_deadline' } }) });
	host.enable();
	sim.tick(2);
	const s = host.state();
	assert.equal(s.mode, 'ai_suspended');
	assert.equal(s.reason, 'policy_deadline');
});

test('정책 모듈은 enable마다 init하고 manual 전환 때 dispose한다', () => {
	const { host, sim } = setup({ policy: false });
	let inits = 0;
	let disposes = 0;
	host.setPolicyModule({
		meta: { id: 'counted', version: '1.0.0' },
		init() {
			inits++;
			return { decide: () => ({ hold: 0 }), reset() {}, dispose() { disposes++; } };
		},
	}, {}, { id: 'counted' });
	assert.equal(host.state().policy.id, 'counted');
	host.enable();
	sim.tick(1);
	host.disable('host_request');
	assert.equal(inits, 1);
	assert.equal(disposes, 1);
	host.enable();
	assert.equal(inits, 2);
	host.suspend('host_request');
	assert.equal(disposes, 1); // 정지만으로는 dispose하지 않는다(resume 대비)
	host.resume();
	assert.equal(inits, 2);
});

test('정책 모듈 init이 던지면 enable은 policy_error를 돌려주고 manual을 유지한다', () => {
	const { host } = setup({ policy: false });
	host.setPolicyModule({ init() { throw new Error('bad config'); } }, {}, { id: 'bad' });
	assert.equal(host.enable(), 'policy_error');
	const s = host.state();
	assert.equal(s.mode, 'manual');
	assert.match(s.lastError.message, /bad config/);
});

test('episode가 바뀌면 정책 reset을 부른다', () => {
	const { host, sim } = setup({ policy: false });
	const resets = [];
	host.setPolicy({ decide: () => ({ hold: 0 }), reset: (why) => resets.push(why) });
	host.enable();
	sim.tick(2);
	sim.newEpisodeWhileActive(); // ai_active → ai_suspended(restart)
	host.resume();
	sim.tick(2);
	assert.ok(resets.includes('enable'));
	assert.ok(resets.includes('resume'));
});

test('개발자 빌드·알 수 없는 빌드는 경고, 릴리스는 경고 없음, mock은 항상 mock 경고', () => {
	const { host } = setup({ kind: 'real' });
	assert.deepEqual(host.state().warnings.map((w) => w.code), ['build_unknown']);
	host.setBuildInfo({ flavor: 'developer', taiseiCommit: 'abc' });
	let s = host.state();
	assert.deepEqual(s.warnings.map((w) => w.code), ['developer_build']);
	assert.equal(s.rulesPreserved, 'unverified');
	host.setBuildInfo({ flavor: 'release' });
	s = host.state();
	assert.deepEqual(s.warnings, []);
	assert.equal(s.rulesPreserved, 'release_build');

	const m = setup({ kind: 'mock' });
	m.host.setBuildInfo({ flavor: 'release' });
	assert.deepEqual(m.host.state().warnings.map((w) => w.code), ['mock_adapter']);
});

test('onEvent 구독 해제와 구독자 예외 격리', () => {
	const { host } = setup();
	let n = 0;
	const off = host.onEvent(() => { n++; });
	host.onEvent(() => { throw new Error('listener'); });
	host.enable();
	const after = n;
	assert.ok(after >= 1);
	off();
	host.disable('host_request');
	assert.equal(n, after);
	assert.equal(host.state().mode, 'manual'); // 구독자 예외가 호스트를 멈추지 않는다
});

test('판단 시간 통계(p50/p95/max)와 프레임 예산 초과 횟수', () => {
	let t = 0;
	const durations = [1, 2, 3, 4, 20];
	let i = 0;
	const host = createHost({ now: () => t });
	const adapter = createMockAdapter();
	host.attach(adapter, 'mock');
	host.setPolicy({ decide() { t += durations[i++ % durations.length]; return { hold: 0 }; } });
	host.enable();
	adapter.sim.tick(6); // 첫 틱 포함 관측 6회
	const d = host.decisionStats();
	assert.equal(d.count, 6);
	assert.equal(d.max_ms, 20);
	assert.ok(d.over_frame >= 1);
	assert.ok(d.p95_ms >= d.p50_ms);
});

test('detach하면 입력 해제를 요청하고 unavailable로 돌아간다', () => {
	const { host, sim } = setup();
	host.enable();
	host.detach();
	assert.equal(host.state().available, false);
	assert.equal(sim.hasPendingSlot(), false);
	assert.equal(host.enable(), 'unavailable');
});

test('어댑터가 인터페이스를 지키지 않으면 attach가 거부한다', () => {
	const host = createHost();
	assert.throws(() => host.attach({ enable() {} }, 'real'), /없습니다/);
	assert.equal(host.state().available, false);
});

test('shot 의미 표기: AI hold.SHOT은 항상 공격, 반전은 물리 키에만', () => {
	const { host } = setup();
	assert.deepEqual(host.state().shotSemantics, { aiHoldShot: 'always_attacking', manualInversion: 'physical_key_only' });
});
