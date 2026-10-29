// Taisei AI 브리지 JS 어댑터 (계약: docs/ai/CONTRACT.md v1, 소유: 세션 2 / 이슈 #21)
//
// 하는 일
//  - fork가 내보낸 `taisei_ai_*` C 함수를 감싼다.
//  - `taisei_ai_layout()`의 JSON을 해석해 관측 버퍼의 TypedArray 뷰를 만든다.
//  - ALLOW_MEMORY_GROWTH로 wasm 힙이 늘어나 ArrayBuffer가 바뀌면 읽기 전에 뷰를 다시 만든다.
//  - 동기 콜백(onFrame)과 비동기 읽기(read/submit)를 같은 계약으로 제공한다.
// 하지 않는 일
//  - 정책 판단, 평가 집계, UI. 이 모듈은 DOM에 의존하지 않는다.

export const ABI_VERSION = 1;
export const OBS_SCHEMA = 'taisei.ai.obs/1';
export const ACT_SCHEMA = 'taisei.ai.act/1';

// 원본 inputflags 비트와 같다 (리플레이 호환 때문에 순서를 바꾸지 않는다)
export const HOLD = Object.freeze({ UP: 1, DOWN: 2, LEFT: 4, RIGHT: 8, FOCUS: 16, SHOT: 32, SKIP: 64 });
export const EDGE = Object.freeze({ BOMB: 1, SPECIAL: 2 });

export const OWNER_STATE = Object.freeze(['manual', 'ai_active', 'ai_suspended']);

// 인덱스가 곧 정수 코드다 (CONTRACT.md 4.2절)
export const REASONS = Object.freeze([
	'none', 'pause', 'focus_lost', 'dialog', 'stage_end', 'restart', 'host_request',
	'user_input', 'policy_error', 'policy_deadline', 'observation_invalid', 'bridge_error',
	'game_over', 'not_playing',
]);

// submit 반환 코드 (CONTRACT.md 6.2절)
export const SUBMIT_STATUS = Object.freeze([
	'accepted', 'stale', 'dup', 'wrong_episode', 'not_active', 'future', 'no_stage',
]);

// enable/resume 반환 코드
export const TRANSITION_RESULT = Object.freeze(['ok', 'not_playing', 'noop']);

export const PHASE = Object.freeze(['normal', 'hit_pending', 'dead', 'recovering', 'bombing']);

export const OVERFLOW = Object.freeze({ BULLETS: 1, LASERS: 2, LASER_SEGS: 4, ENEMIES: 8 });

// 계약이 요구하는 필드. 레이아웃에 이 이름과 형이 모두 있어야 한다 (추가 필드는 허용).
export const FIELDS = Object.freeze({
	i32: [
		'schema_ver', 'frame', 'episode_id', 'stage_id', 'stage_type', 'difficulty', 'practice',
		'replay_mode', 'skip_mode', 'gameover', 'paused', 'dialog_active', 'seed_lo', 'seed_hi',
		'seed_source', 'cheat_flags', 'cheat_events', 'overflow', 'n_bullets', 'n_lasers', 'n_segs',
		'n_enemies', 'total_bullets', 'total_lasers', 'total_segs', 'total_enemies', 'owner_state',
		'owner_reason', 'owner_events', 'act_applied', 'act_stale', 'act_dup', 'act_missing',
		'act_rejected', 'act_last_obs_frame', 'hold_applied',
		'p_alive', 'p_vulnerable', 'p_phase', 'p_inputflags', 'p_focus', 'p_lives', 'p_bombs',
		'p_power', 'p_power_stored', 'p_graze', 'p_deathtime', 'p_respawntime', 'p_recoverytime',
		'p_bomb_endtime', 'p_bomb_active', 'p_powersurge', 'p_ev_hit', 'p_ev_death',
		'p_ev_death_uncounted', 'p_ev_bomb', 'p_continues_used',
		'b_present', 'b_attack_type',
	],
	f32: [
		'p_x', 'p_y', 'p_vx', 'p_vy', 'p_speed_normal', 'p_speed_focus', 'p_hit_radius',
		'b_hp', 'b_maxhp', 'b_x', 'b_y',
	],
	arrays: {
		bullets: {
			count: 'n_bullets',
			fields: {
				id: 'u32', x: 'f32', y: 'f32', px: 'f32', py: 'f32', wx: 'f32', wy: 'f32', angle: 'f32',
				vx: 'f32', vy: 'f32', ax: 'f32', ay: 'f32', ret_re: 'f32', ret_im: 'f32',
				attr_re: 'f32', attr_im: 'f32', attr_x: 'f32', attr_y: 'f32', attr_exp: 'f32',
				flags: 'u32', age: 'i32',
			},
		},
		lasers: {
			count: 'n_lasers',
			fields: {
				id: 'u32', active: 'u32', birth: 'i32', timespan: 'f32', deathtime: 'f32',
				speed: 'f32', width: 'f32', seg_start: 'u32', seg_count: 'u32',
			},
		},
		laser_segs: {
			count: 'n_segs',
			fields: { ax: 'f32', ay: 'f32', bx: 'f32', by: 'f32', ra: 'f32', rb: 'f32' },
		},
		enemies: {
			count: 'n_enemies',
			fields: { id: 'u32', x: 'f32', y: 'f32', hurt_radius: 'f32', hp: 'f32', flags: 'u32' },
		},
	},
	// 정지 중에도 읽는 작은 블록 (CONTRACT.md 6.4절)
	status: [
		'in_stage', 'paused', 'episode_id', 'last_frame', 'owner_state', 'owner_reason',
		'owner_events', 'replay_mode', 'gameover', 'observe',
	],
});

const TYPED = { i32: Int32Array, u32: Uint32Array, f32: Float32Array };

export class BridgeError extends Error {
	constructor(message, code) {
		super(message);
		this.name = 'BridgeError';
		this.code = code;
	}
}

// 레이아웃이 계약 필드를 모두 갖췄는지 검사한다. 문제 목록을 돌려준다 (비어 있으면 통과).
export function validateLayout(layout) {
	const problems = [];

	if (!layout || typeof layout !== 'object') {
		return ['레이아웃이 객체가 아니다'];
	}

	if (layout.schema !== OBS_SCHEMA) {
		problems.push(`schema 불일치: ${layout.schema} (기대 ${OBS_SCHEMA})`);
	}

	if (layout.abi !== ABI_VERSION) {
		problems.push(`abi 불일치: ${layout.abi} (기대 ${ABI_VERSION})`);
	}

	if (!Number.isInteger(layout.base) || layout.base <= 0 || layout.base % 4 !== 0) {
		problems.push('base가 4바이트 정렬된 양의 정수가 아니다');
	}

	const checkBlock = (name, wanted, type) => {
		const block = layout[name];
		if (!block || !block.fields) {
			problems.push(`${name} 블록 없음`);
			return;
		}
		if (block.type !== undefined && block.type !== type) {
			problems.push(`${name}.type이 ${block.type}이다 (기대 ${type})`);
		}
		for (const f of wanted) {
			if (!Number.isInteger(block.fields[f])) {
				problems.push(`${name}.fields.${f} 없음`);
			} else if (block.fields[f] < 0 || block.fields[f] >= block.count) {
				problems.push(`${name}.fields.${f} 인덱스가 범위를 벗어남`);
			}
		}
	};

	checkBlock('i32', FIELDS.i32, 'i32');
	checkBlock('f32', FIELDS.f32, 'f32');
	checkBlock('status', FIELDS.status, 'i32');

	for (const [gname, g] of Object.entries(FIELDS.arrays)) {
		const lg = layout.arrays?.[gname];
		if (!lg) {
			problems.push(`arrays.${gname} 없음`);
			continue;
		}
		if (!Number.isInteger(lg.max) || lg.max <= 0) {
			problems.push(`arrays.${gname}.max가 잘못됨`);
		}
		if (lg.count_field !== g.count) {
			problems.push(`arrays.${gname}.count_field가 ${lg.count_field}이다 (기대 ${g.count})`);
		}
		for (const [fname, ftype] of Object.entries(g.fields)) {
			const lf = lg.fields?.[fname];
			if (!lf) {
				problems.push(`arrays.${gname}.${fname} 없음`);
			} else if (lf.type !== ftype) {
				problems.push(`arrays.${gname}.${fname} 형이 ${lf.type}이다 (기대 ${ftype})`);
			} else if (!Number.isInteger(lf.offset) || lf.offset % 4 !== 0) {
				problems.push(`arrays.${gname}.${fname} 오프셋이 4바이트 정렬이 아님`);
			}
		}
	}

	return problems;
}

// hold 입력을 비트로 바꾼다. 숫자, 이름 배열(['LEFT','FOCUS']), 객체({left:true}) 모두 받는다.
export function holdBits(hold) {
	if (hold == null) return 0;
	if (typeof hold === 'number') return hold & 0x7f;

	let bits = 0;
	if (Array.isArray(hold)) {
		for (const name of hold) bits |= bitByName(HOLD, name, 'hold');
	} else {
		for (const [name, on] of Object.entries(hold)) {
			if (on) bits |= bitByName(HOLD, name, 'hold');
		}
	}
	return bits;
}

export function edgeBits(edges) {
	if (edges == null) return 0;
	if (typeof edges === 'number') return edges & 0x3;

	let bits = 0;
	if (Array.isArray(edges)) {
		for (const name of edges) bits |= bitByName(EDGE, name, 'edges');
	} else {
		for (const [name, on] of Object.entries(edges)) {
			if (on) bits |= bitByName(EDGE, name, 'edges');
		}
	}
	return bits;
}

function bitByName(table, name, what) {
	const bit = table[String(name).toUpperCase()];
	if (bit === undefined) {
		throw new BridgeError(`알 수 없는 ${what} 이름: ${name}`, 'bad_action');
	}
	return bit;
}

export function reasonCode(reason) {
	if (typeof reason === 'number') {
		if (!Number.isInteger(reason) || reason < 0 || reason >= REASONS.length) {
			throw new BridgeError(`알 수 없는 사유 코드: ${reason}`, 'bad_reason');
		}
		return reason;
	}
	const i = REASONS.indexOf(reason);
	if (i < 0) {
		throw new BridgeError(`알 수 없는 사유: ${reason}`, 'bad_reason');
	}
	return i;
}

export function reasonName(code) {
	return REASONS[code] ?? `unknown(${code})`;
}

function group(name) {
	if (name.startsWith('p_')) return ['player', name.slice(2)];
	if (name.startsWith('b_')) return ['boss', name.slice(2)];
	return ['meta', name];
}

export class TaiseiAIBridge {
	constructor(Module, options = {}) {
		this.M = Module;
		this._prefix = options.prefix ?? '_taisei_ai_';
		this._buf = null;
		this.viewGeneration = 0;
		this._errors = [];
		this._frameCb = null;
		this._eventCb = null;

		const abi = this._call('abi_version');
		if (abi !== ABI_VERSION) {
			throw new BridgeError(`ABI 버전 불일치: ${abi} (기대 ${ABI_VERSION})`, 'abi_mismatch');
		}

		this.layout = this._readLayout();
		const problems = validateLayout(this.layout);
		if (problems.length) {
			throw new BridgeError(`레이아웃이 계약과 맞지 않음:\n- ${problems.join('\n- ')}`, 'layout_mismatch');
		}

		this.refresh();
	}

	// ---- C 함수 호출 ------------------------------------------------------

	_fn(name) {
		const fn = this.M[this._prefix + name];
		if (typeof fn !== 'function') {
			throw new BridgeError(`내보낸 함수 없음: ${this._prefix}${name}`, 'missing_export');
		}
		return fn;
	}

	_call(name, ...args) {
		return this._fn(name)(...args);
	}

	// ---- 메모리 ----------------------------------------------------------

	_currentBuffer() {
		const mem = this.M.wasmMemory;
		if (mem && mem.buffer) return mem.buffer;
		if (this.M.HEAPU8) return this.M.HEAPU8.buffer;
		throw new BridgeError('wasm 메모리에 접근할 수 없다 (wasmMemory 또는 HEAPU8 필요)', 'no_memory');
	}

	_readLayout() {
		const ptr = this._call('layout');
		const size = this._call('layout_size');
		const buf = this._currentBuffer();
		const bytes = new Uint8Array(buf, ptr, size);
		return JSON.parse(new TextDecoder('utf-8').decode(bytes));
	}

	// 힙이 늘어나 버퍼가 바뀌었으면 모든 뷰를 다시 만든다. 바뀌었으면 true.
	refresh() {
		const buf = this._currentBuffer();
		if (buf === this._buf) return false;

		this._buf = buf;
		this.viewGeneration++;
		const L = this.layout;
		const at = (off) => L.base + off;

		this.i32 = new Int32Array(buf, at(L.i32.offset), L.i32.count);
		this.f32 = new Float32Array(buf, at(L.f32.offset), L.f32.count);
		this.statusView = new Int32Array(buf, at(L.status.offset), L.status.count);

		this.arrays = {};
		for (const [gname, g] of Object.entries(L.arrays)) {
			const views = {};
			for (const [fname, f] of Object.entries(g.fields)) {
				views[fname] = new TYPED[f.type](buf, at(f.offset), g.max);
			}
			this.arrays[gname] = views;
		}

		this._obs = this._makeObs();
		return true;
	}

	_makeObs() {
		const obs = { meta: {}, player: {}, boss: {} };
		for (const gname of Object.keys(this.arrays)) {
			obs[gname] = { n: 0, ...this.arrays[gname] };
		}
		return obs;
	}

	// ---- 읽기 ------------------------------------------------------------

	// 현재 관측을 읽는다. 복사가 없으므로 배열은 다음 캡처 전까지만 유효하다.
	// 반환 객체는 호출마다 재사용된다 (보관하려면 snapshot()).
	read() {
		this.refresh();

		const L = this.layout;
		const obs = this._obs;

		for (const [name, idx] of Object.entries(L.i32.fields)) {
			const [g, key] = group(name);
			obs[g][key] = this.i32[idx];
		}
		for (const [name, idx] of Object.entries(L.f32.fields)) {
			const [g, key] = group(name);
			obs[g][key] = this.f32[idx];
		}

		const m = obs.meta;
		for (const [gname, g] of Object.entries(FIELDS.arrays)) {
			obs[gname].n = Math.min(m[g.count], L.arrays[gname].max);
		}

		obs.meta.owner = OWNER_STATE[m.owner_state] ?? 'unknown';
		obs.meta.owner_reason_name = reasonName(m.owner_reason);
		obs.player.phase_name = PHASE[obs.player.phase] ?? 'unknown';
		return obs;
	}

	// 보관용 복사본. 배열은 실제 개수만큼 잘라 복사한다.
	snapshot() {
		const o = this.read();
		const out = {
			meta: { ...o.meta },
			player: { ...o.player },
			boss: { ...o.boss },
		};
		for (const [gname, g] of Object.entries(FIELDS.arrays)) {
			const src = o[gname];
			const dst = { n: src.n };
			for (const fname of Object.keys(g.fields)) {
				dst[fname] = src[fname].slice(0, src.n);
			}
			out[gname] = dst;
		}
		return out;
	}

	// 정지·메뉴 중에도 최신인 상태 블록.
	state() {
		this.refresh();
		const s = {};
		for (const [name, idx] of Object.entries(this.layout.status.fields)) {
			s[name] = this.statusView[idx];
		}
		s.owner = OWNER_STATE[s.owner_state] ?? 'unknown';
		s.owner_reason_name = reasonName(s.owner_reason);
		return s;
	}

	// ---- 제어 ------------------------------------------------------------

	setObserve(on) {
		this._call('set_observe', on ? 1 : 0);
	}

	enable() {
		return TRANSITION_RESULT[this._call('enable')] ?? 'error';
	}

	resume() {
		return TRANSITION_RESULT[this._call('resume')] ?? 'error';
	}

	suspend(reason = 'host_request') {
		this._call('suspend', reasonCode(reason));
	}

	disable(reason = 'host_request') {
		this._call('disable', reasonCode(reason));
	}

	requestRestart() {
		this._call('request_restart');
	}

	// seed: bigint 또는 [lo, hi]. 상위/하위 32비트로 나눠 넘긴다.
	setSeed(seed, { sticky = false } = {}) {
		let lo;
		let hi;
		if (Array.isArray(seed)) {
			[lo, hi] = seed;
		} else {
			const b = BigInt.asUintN(64, BigInt(seed));
			lo = Number(b & 0xffffffffn);
			hi = Number(b >> 32n);
		}
		this._call('set_seed', lo | 0, hi | 0, sticky ? 1 : 0);
	}

	clearSeed() {
		this._call('clear_seed');
	}

	// 액션을 제출한다. episode_id/target_frame을 생략하면 마지막 관측 기준(+1)으로 채운다.
	submit(action = {}) {
		this.refresh();
		const hold = holdBits(action.hold);
		const edges = edgeBits(action.edges);
		const ep = action.episode_id ?? this.i32[this.layout.i32.fields.episode_id];
		const target = action.target_frame ?? this.i32[this.layout.i32.fields.frame] + 1;
		const code = this._call('submit', ep | 0, target | 0, hold, edges);
		return SUBMIT_STATUS[code] ?? `unknown(${code})`;
	}

	// ---- 콜백 ------------------------------------------------------------

	// 동기 콜백: 캡처 직후 같은 틱 안에서 cb(obs, ctl)를 부른다. ctl.submit은 frame+1로 제출한다.
	// 콜백이 예외를 던지면 `policy_error`로 manual 전환하고 오류를 기록한다.
	onFrame(cb) {
		if (cb === null) {
			this._frameCb = null;
			delete this.M.taiseiAIOnFrame;
			return;
		}

		this._frameCb = cb;
		this.M.taiseiAIOnFrame = (frame, episodeId) => {
			const ctl = {
				frame,
				episode_id: episodeId,
				submit: (action = {}) =>
					this.submit({ ...action, episode_id: episodeId, target_frame: frame + 1 }),
			};

			try {
				cb(this.read(), ctl);
			} catch (e) {
				this._errors.push(e);
				try {
					this.disable('policy_error');
				} catch (e2) {
					this._errors.push(e2);
				}
			}
		};
	}

	// 소유권 전환 알림: cb(kind, stateName, reasonName). kind 0 = 전환.
	onEvent(cb) {
		if (cb === null) {
			this._eventCb = null;
			delete this.M.taiseiAIOnEvent;
			return;
		}

		this._eventCb = cb;
		this.M.taiseiAIOnEvent = (kind, state, reason) => {
			try {
				cb(kind, OWNER_STATE[state] ?? 'unknown', reasonName(reason));
			} catch (e) {
				this._errors.push(e);
			}
		};
	}

	// 콜백에서 쌓인 오류를 꺼낸다.
	takeErrors() {
		const e = this._errors;
		this._errors = [];
		return e;
	}
}

export function createBridge(Module, options) {
	return new TaiseiAIBridge(Module, options);
}
