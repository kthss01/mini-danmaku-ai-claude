// 어댑터 fixture 테스트. 실제 게임 결과가 아니라 어댑터 로직만 검증한다.
// 실행: node --test tests/ai-bridge/
import test from 'node:test';
import assert from 'node:assert/strict';

import {
	createBridge, BridgeError, validateLayout, holdBits, edgeBits, reasonCode, reasonName,
	HOLD, EDGE, REASONS, OVERFLOW,
} from '../../ai/bridge/taisei-ai-bridge.mjs';
import { createMockModule } from './mock-module.mjs';

function fillSample({ i32, f32, fi, ff, arr }) {
	i32[fi.overflow] = 0;
	i32[fi.n_bullets] = 2;
	i32[fi.total_bullets] = 2;
	i32[fi.p_phase] = 3;
	i32[fi.p_lives] = 2;
	f32[ff.p_x] = 240.5;
	f32[ff.p_y] = 496;
	arr('bullets', 'id').set([101, 102]);
	arr('bullets', 'x').set([10.5, 20.25]);
	arr('bullets', 'wx').set([8, 16]);
	arr('bullets', 'flags').set([1, 0]);
	arr('bullets', 'age').set([-3, 7]);
}

test('레이아웃 해석 후 메타·플레이어·배열 필드를 읽는다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	M.__tick(fillSample);

	const o = b.read();
	assert.equal(o.meta.frame, 0);
	assert.equal(o.meta.episode_id, 1);
	assert.equal(o.player.lives, 2);
	assert.equal(o.player.phase_name, 'recovering');
	assert.ok(Math.abs(o.player.x - 240.5) < 1e-6);
	assert.equal(o.bullets.n, 2);
	assert.equal(o.bullets.id[1], 102);
	assert.equal(o.bullets.x[0], 10.5);
	assert.equal(o.bullets.wx[1], 16);
	assert.equal(o.bullets.age[0], -3, '부호 있는 정수는 Int32로 읽는다');
});

test('u32 필드(id)는 2^31 이상도 부호 없이 읽는다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	M.__tick(({ i32, fi, arr }) => {
		i32[fi.n_bullets] = 1;
		arr('bullets', 'id')[0] = 0xfffffff0;
	});
	assert.equal(b.read().bullets.id[0], 0xfffffff0);
});

test('힙이 늘어나 ArrayBuffer가 바뀌면 뷰를 다시 만들고 값을 계속 읽는다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	M.__tick(fillSample);

	const before = b.read();
	const oldX = before.bullets.x;
	const gen = b.viewGeneration;
	assert.equal(oldX.length, 8);

	M.__grow(2);
	// 낡은 뷰는 분리되어 길이 0이 된다 — 계약 3절이 말하는 위험
	assert.equal(oldX.length, 0);
	assert.equal(oldX.buffer.byteLength, 0);

	M.__tick(fillSample);
	const after = b.read();
	assert.equal(b.viewGeneration, gen + 1, '버퍼가 바뀌면 정확히 한 번 재생성');
	assert.equal(after.bullets.x.length, 8);
	assert.equal(after.bullets.x[1], 20.25);
	assert.equal(after.meta.frame, 1);

	// 버퍼가 그대로면 재생성하지 않는다
	b.read();
	assert.equal(b.viewGeneration, gen + 1);
});

test('힙 증가는 submit·state에서도 처리한다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	M.__tick(fillSample);
	b.enable();
	M.__grow(1);
	assert.equal(b.state().owner, 'ai_active');
	M.__grow(1);
	assert.equal(b.submit({ hold: ['LEFT'] }), 'accepted');
});

test('snapshot은 실제 개수만큼 복사하고 이후 덮어쓰기와 분리된다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	M.__tick(fillSample);
	const snap = b.snapshot();
	assert.equal(snap.bullets.x.length, 2);
	assert.deepEqual(Array.from(snap.bullets.id), [101, 102]);

	M.__tick(({ i32, fi, arr }) => {
		i32[fi.n_bullets] = 1;
		arr('bullets', 'id')[0] = 999;
	});
	assert.equal(snap.bullets.id[0], 101);
	assert.equal(snap.meta.frame, 0);
});

test('개수가 최대를 넘는 값이 와도 n은 최대로 자른다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	M.__tick(({ i32, fi }) => {
		i32[fi.n_bullets] = 9999;
		i32[fi.total_bullets] = 9999;
		i32[fi.overflow] = OVERFLOW.BULLETS;
	});
	const o = b.read();
	assert.equal(o.bullets.n, 8);
	assert.equal(o.meta.total_bullets, 9999);
	assert.equal(o.meta.overflow & OVERFLOW.BULLETS, OVERFLOW.BULLETS);
});

test('레이아웃·ABI 불일치는 생성 시 BridgeError', () => {
	assert.throws(() => createBridge(createMockModule({ abi: 2 })), (e) => e instanceof BridgeError && e.code === 'abi_mismatch');
	assert.throws(() => createBridge(createMockModule({ schema: 'taisei.ai.obs/0' })), (e) => e.code === 'layout_mismatch');
	assert.throws(() => createBridge(createMockModule({ dropI32: 'frame' })), (e) => e.code === 'layout_mismatch' && /i32\.fields\.frame/.test(e.message));
	assert.throws(() => createBridge(createMockModule({ badType: 'bullets.x' })), (e) => e.code === 'layout_mismatch' && /bullets\.x/.test(e.message));

	const M = createMockModule();
	delete M._taisei_ai_layout;
	assert.throws(() => createBridge(M), (e) => e.code === 'missing_export');
});

test('validateLayout은 정상 레이아웃에서 문제가 없다', () => {
	const M = createMockModule();
	assert.deepEqual(validateLayout(M.__layout), []);
	assert.ok(validateLayout(null).length > 0);
});

test('hold/edges 인코딩', () => {
	assert.equal(holdBits(['left', 'FOCUS', 'shot']), HOLD.LEFT | HOLD.FOCUS | HOLD.SHOT);
	assert.equal(holdBits({ up: true, down: false, right: true }), HOLD.UP | HOLD.RIGHT);
	assert.equal(holdBits(0xff), 0x7f, '정의되지 않은 비트는 버린다');
	assert.equal(holdBits(null), 0);
	assert.equal(edgeBits(['bomb']), EDGE.BOMB);
	assert.equal(edgeBits({ special: true }), EDGE.SPECIAL);
	assert.throws(() => holdBits(['JUMP']), (e) => e.code === 'bad_action');
	assert.throws(() => edgeBits(['bomb2']), (e) => e.code === 'bad_action');
});

test('사유 코드는 이름과 정수가 일대일이다', () => {
	assert.equal(REASONS.length, 15);
	assert.equal(new Set(REASONS).size, 15);
	assert.equal(REASONS[14], 'action_timeout');
	for (let i = 0; i < REASONS.length; i++) {
		assert.equal(reasonCode(REASONS[i]), i);
		assert.equal(reasonName(i), REASONS[i]);
	}
	assert.equal(reasonCode('user_input'), 7);
	assert.throws(() => reasonCode('nope'), (e) => e.code === 'bad_reason');
	assert.throws(() => reasonCode(99), (e) => e.code === 'bad_reason');
});

test('제출: 관측 프레임 + 1이 기본이고 상태 코드를 이름으로 돌려준다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	assert.equal(b.submit({ hold: ['LEFT'] }), 'not_active');

	assert.equal(b.enable(), 'ok');
	M.__tick(fillSample); // frame 0 관측
	assert.equal(b.submit({ hold: ['LEFT'], edges: ['BOMB'] }), 'accepted');
	assert.equal(b.submit({ hold: ['RIGHT'] }), 'dup');
	assert.equal(b.submit({ target_frame: 5 }), 'future');
	assert.equal(b.submit({ episode_id: 77 }), 'wrong_episode');
	const call = M.__state.calls[1];
	assert.equal(call.target, 1);
	assert.equal(call.hold, HOLD.LEFT);
	assert.equal(call.edges, EDGE.BOMB);

	M.__tick(fillSample); // 프레임 1에서 적용
	assert.equal(M.__state.applied.length, 1);
	assert.equal(b.submit({ target_frame: 0 }), 'stale');
});

test('동기 콜백: 같은 틱에서 제출하고 다음 틱에 적용된다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	const seen = [];
	b.onFrame((obs, ctl) => {
		seen.push(obs.meta.frame);
		assert.equal(ctl.submit({ hold: ['LEFT'] }), 'accepted');
	});
	b.enable();
	for (let i = 0; i < 4; i++) M.__tick(fillSample);

	assert.deepEqual(seen, [0, 1, 2, 3]);
	// 프레임 0의 액션은 프레임 1에 적용 → 마지막까지 3개 적용, missing 없음
	assert.equal(M.__state.applied.length, 3);
	assert.equal(b.read().meta.act_missing, 0);
});

test('콜백이 예외를 던지면 policy_error로 manual 전환하고 오류를 기록한다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	b.onFrame(() => {
		throw new Error('정책 실패');
	});
	b.enable();
	M.__tick(fillSample);

	const s = b.state();
	assert.equal(s.owner, 'manual');
	assert.equal(s.owner_reason_name, 'policy_error');
	const errs = b.takeErrors();
	assert.equal(errs.length, 1);
	assert.match(errs[0].message, /정책 실패/);
	assert.equal(b.takeErrors().length, 0);
});

test('전환 이벤트 콜백과 대기 액션 폐기', () => {
	const M = createMockModule();
	const b = createBridge(M);
	const events = [];
	b.onEvent((kind, state, reason) => events.push([kind, state, reason]));

	b.enable();
	M.__tick(fillSample);
	assert.equal(b.submit({ hold: ['UP'] }), 'accepted');
	b.suspend('pause');
	assert.equal(M.__state.slot, null, '전환하면 대기 슬롯을 버린다');
	b.resume();
	b.disable('user_input');

	assert.deepEqual(events, [
		[0, 'ai_active', 'host_request'],
		[0, 'ai_suspended', 'pause'],
		[0, 'ai_active', 'host_request'],
		[0, 'manual', 'user_input'],
	]);
	assert.equal(b.state().owner_events, 4);
});

test('진행 중인 스테이지가 아니면 enable은 ai_suspended(not_playing)', () => {
	const M = createMockModule({ playing: false });
	const b = createBridge(M);
	assert.equal(b.enable(), 'not_playing');
	const s = b.state();
	assert.equal(s.owner, 'ai_suspended');
	assert.equal(s.owner_reason_name, 'not_playing');
	assert.equal(b.resume(), 'not_playing');
});

test('시드 설정: bigint를 상·하위 32비트로 나눈다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	b.setSeed(0x1122334455667788n, { sticky: true });
	assert.deepEqual(M.__state.seed, { lo: 0x55667788, hi: 0x11223344, sticky: true });
	b.setSeed([1, 2]);
	assert.deepEqual(M.__state.seed, { lo: 1, hi: 2, sticky: false });
	b.clearSeed();
	assert.equal(M.__state.seed, null);
});

test('누락 허용 한도와 캡처 상한 설정이 C 함수 인자로 전달된다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	b.setMissingLimit(10);
	assert.equal(M.__state.missingLimit, 10);
	b.setMissingLimit(-1);
	assert.equal(M.__state.missingLimit, -1, '음수는 C 쪽이 기본값으로 되돌린다');
	b.setLimits({ bullets: 5, segs: 3 });
	assert.deepEqual(M.__state.limits, [5, 0, 3, 0]);
	b.setLimits();
	assert.deepEqual(M.__state.limits, [0, 0, 0, 0]);
});

test('action_timeout 전환 이벤트는 이름으로 전달된다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	const events = [];
	b.onEvent((k, s, r) => events.push([s, r]));
	b.enable();
	b.suspend('action_timeout');
	assert.deepEqual(events.at(-1), ['ai_suspended', 'action_timeout']);
	assert.equal(b.state().owner_reason_name, 'action_timeout');
});

test('상태 블록은 관측이 없어도 읽는다', () => {
	const M = createMockModule();
	const b = createBridge(M);
	b.setObserve(true);
	const s = b.state();
	assert.equal(s.in_stage, 1);
	assert.equal(s.observe, 1);
	assert.equal(s.owner, 'manual');
});
