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
