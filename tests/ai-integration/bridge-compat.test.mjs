// 호스트(web/game/ai-host.js) ↔ 실제 브리지 어댑터(ai/bridge/taisei-ai-bridge.mjs, 세션 2) 호환 검증.
// 어댑터와 그 fixture(tests/ai-bridge/mock-module.mjs)가 main에 있을 때만 실행한다(없으면 건너뜀).
// 가짜 Module을 쓰는 fixture 검증이므로 "mock 성공"이며 실제 게임 결과가 아니다.
// 실행: node --test tests/ai-integration/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const bridgeUrl = new URL('../../ai/bridge/taisei-ai-bridge.mjs', import.meta.url).href;
const mockUrl = new URL('../ai-bridge/mock-module.mjs', import.meta.url).href;
const available = existsSync(fileURLToPath(bridgeUrl)) && existsSync(fileURLToPath(mockUrl));
const skip = available ? false : 'ai/bridge 어댑터가 아직 main에 없다(세션 2 계약 PR 대기)';

const { createHost } = require('../../web/game/ai-host.js');
const { createSweepPolicy, HOLD } = require('./mock-adapter.js');

async function setup(moduleOptions) {
	const { createBridge } = await import(bridgeUrl);
	const { createMockModule } = await import(mockUrl);
	const M = createMockModule(moduleOptions);
	const host = createHost();
	host.attach(createBridge(M), 'real');
	host.setPolicy(createSweepPolicy());
	return { host, M };
}

test('실제 어댑터: enable → 프레임 콜백 → 정책 액션이 다음 프레임 슬롯에 들어간다', { skip }, async () => {
	const { host, M } = await setup();
	assert.equal(host.enable(), 'ok');
	assert.equal(host.state().mode, 'ai_active');
	M.__tick();
	M.__tick();
	M.__tick();
	const calls = M.__state.calls;
	assert.ok(calls.length >= 3);
	assert.ok(calls.every((c) => (c.hold & HOLD.SHOT) !== 0));
	assert.ok(M.__state.applied.length >= 2);
	assert.ok(host.decisionStats().count >= 3);
});

test('실제 어댑터: 포커스 상실은 ai_suspended(focus_lost)이고 슬롯을 버린다', { skip }, async () => {
	const { host, M } = await setup();
	host.enable();
	M.__tick();
	assert.ok(M.__state.slot, '다음 프레임 액션이 대기 중이어야 한다');
	assert.equal(host.notifyFocusLost(), 'ok');
	const s = host.state();
	assert.equal(s.mode, 'ai_suspended');
	assert.equal(s.reason, 'focus_lost');
	assert.equal(M.__state.slot, null);
	assert.equal(host.resume(), 'ok');
});

test('실제 어댑터: 스테이지 밖 enable은 not_playing, 사유 코드 문자열이 일치한다', { skip }, async () => {
	const { host } = await setup({ playing: false });
	assert.equal(host.enable(), 'not_playing');
	const s = host.state();
	assert.equal(s.mode, 'ai_suspended');
	assert.equal(s.reason, 'not_playing');
	assert.ok(s.reasonInfo.text.length > 0);
});

test('실제 어댑터: 정책 예외는 manual(policy_error)로 전환한다', { skip }, async () => {
	const { createBridge } = await import(bridgeUrl);
	const { createMockModule } = await import(mockUrl);
	const M = createMockModule();
	const host = createHost();
	host.attach(createBridge(M), 'real');
	host.setPolicy({ decide() { throw new Error('boom'); } }, { id: 'broken' });
	host.enable();
	M.__tick();
	const s = host.state();
	assert.equal(s.mode, 'manual');
	assert.equal(s.reason, 'policy_error');
	assert.match(s.lastError.message, /boom/);
});

test('실제 어댑터: 호스트 사유 코드는 모두 브리지 REASONS 안에 있다', { skip }, async () => {
	const { REASONS } = await import(bridgeUrl);
	const { REASON_INFO, HOST_REASONS } = require('../../web/game/ai-host.js');
	assert.deepEqual(Object.keys(REASON_INFO).sort(), [...REASONS].sort());
	for (const r of HOST_REASONS) assert.ok(REASONS.includes(r), r);
});

test('실제 어댑터: edges(BOMB|SPECIAL)와 hold가 submit까지 그대로 전달된다', { skip }, async () => {
	const { createBridge } = await import(bridgeUrl);
	const { createMockModule } = await import(mockUrl);
	const M = createMockModule();
	const host = createHost();
	host.attach(createBridge(M), 'real');
	host.setPolicy({ decide: () => ({ hold: HOLD.SHOT | HOLD.LEFT, edges: 3, request: null }) });
	host.enable();
	M.__tick();
	M.__tick();
	const last = M.__state.calls.at(-1);
	assert.equal(last.hold, HOLD.SHOT | HOLD.LEFT);
	assert.equal(last.edges, 3);
	assert.equal(host.decisionStats().submit.accepted >= 1, true);
});

test('실제 어댑터: request.release는 hold 0·edges 0을 제출하고 소유권을 유지한다', { skip }, async () => {
	const { createBridge } = await import(bridgeUrl);
	const { createMockModule } = await import(mockUrl);
	const M = createMockModule();
	const host = createHost();
	host.attach(createBridge(M), 'real');
	host.setPolicy({ decide: () => ({ hold: HOLD.LEFT, edges: 3, request: { type: 'release', reason: 'observation_invalid' } }) });
	host.enable();
	M.__tick();
	M.__tick();
	const last = M.__state.calls.at(-1);
	assert.equal(last.hold, 0);
	assert.equal(last.edges, 0);
	assert.equal(host.state().mode, 'ai_active');
});

test('실제 어댑터: request.suspend는 hold 0 제출 뒤 ai_suspended(policy_deadline)로 올린다', { skip }, async () => {
	const { createBridge } = await import(bridgeUrl);
	const { createMockModule } = await import(mockUrl);
	const M = createMockModule();
	const host = createHost();
	host.attach(createBridge(M), 'real');
	host.setPolicy({ decide: () => ({ hold: HOLD.LEFT, edges: 3, request: { type: 'suspend', reason: 'policy_deadline' } }) });
	host.enable();
	M.__tick();
	const s = host.state();
	assert.equal(s.mode, 'ai_suspended');
	assert.equal(s.reason, 'policy_deadline');
	assert.equal(M.__state.slot, null);
	const last = M.__state.calls.at(-1);
	assert.equal(last.hold, 0);
	assert.equal(last.edges, 0);
});

test('실제 어댑터: 활성 중 정책 교체는 슬롯을 비우고 manual로 전환한다', { skip }, async () => {
	const { host, M } = await setup();
	host.enable();
	M.__tick();
	assert.ok(M.__state.slot);
	host.setPolicy(null);
	assert.equal(host.state().mode, 'manual');
	assert.equal(M.__state.slot, null);
});
