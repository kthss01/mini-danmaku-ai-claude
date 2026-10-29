// 어댑터 fixture용 가짜 Emscripten Module.
// 실제 게임이 아니다. 계약(docs/ai/CONTRACT.md)의 레이아웃 JSON 형식과 함수 시그니처를 흉내 내서
// 어댑터의 뷰 재생성·레이아웃 해석·제출 인코딩·콜백 처리를 검증한다.
import { FIELDS, REASONS } from '../../ai/bridge/taisei-ai-bridge.mjs';

const PAGE = 65536;
const MAX = { bullets: 8, lasers: 2, laser_segs: 4, enemies: 3 };

export function createMockModule(options = {}) {
	const memory = new WebAssembly.Memory({ initial: 4, maximum: 64 });
	const M = { wasmMemory: memory };

	// 힙을 흉내 내서 base를 0이 아닌 값으로 둔다
	const base = options.base ?? 1024;
	let cursor = 0;
	const alloc = (bytes) => {
		const off = cursor;
		cursor += bytes;
		return off;
	};

	const layout = {
		schema: options.schema ?? 'taisei.ai.obs/1',
		abi: options.layoutAbi ?? 1,
		base,
		size: 0,
		i32: { offset: 0, count: 0, fields: {} },
		f32: { offset: 0, count: 0, fields: {} },
		status: { offset: 0, count: 0, fields: {} },
		arrays: {},
		enums: { owner_reason: [...REASONS] },
	};

	const i32Names = options.dropI32
		? FIELDS.i32.filter((n) => n !== options.dropI32)
		: FIELDS.i32;

	layout.i32.offset = alloc(i32Names.length * 4);
	layout.i32.count = i32Names.length;
	i32Names.forEach((n, i) => (layout.i32.fields[n] = i));

	layout.f32.offset = alloc(FIELDS.f32.length * 4);
	layout.f32.count = FIELDS.f32.length;
	FIELDS.f32.forEach((n, i) => (layout.f32.fields[n] = i));

	layout.status.offset = alloc(FIELDS.status.length * 4);
	layout.status.count = FIELDS.status.length;
	FIELDS.status.forEach((n, i) => (layout.status.fields[n] = i));

	for (const [gname, g] of Object.entries(FIELDS.arrays)) {
		const max = MAX[gname];
		const lg = { max, count_field: g.count, fields: {} };
		for (const [fname, type] of Object.entries(g.fields)) {
			lg.fields[fname] = { type: options.badType === `${gname}.${fname}` ? 'u32' : type, offset: alloc(max * 4) };
		}
		layout.arrays[gname] = lg;
	}

	layout.size = cursor;

	// 레이아웃 JSON은 obs 영역 뒤에 둔다
	const json = new TextEncoder().encode(JSON.stringify(layout));
	const jsonPtr = base + cursor;
	new Uint8Array(memory.buffer).set(json, jsonPtr);

	const state = {
		observe: false,
		owner: 0,
		reason: 0,
		events: 0,
		frame: 0,
		lastObs: -1,
		episode: 1,
		slot: null,
		applied: [],
		seed: null,
		restarts: 0,
		calls: [],
		playing: options.playing ?? true,
	};

	const i32 = () => new Int32Array(memory.buffer, base + layout.i32.offset, layout.i32.count);
	const f32 = () => new Float32Array(memory.buffer, base + layout.f32.offset, layout.f32.count);
	const st = () => new Int32Array(memory.buffer, base + layout.status.offset, layout.status.count);
	const arr = (g, f) => {
		const lf = layout.arrays[g].fields[f];
		const T = { i32: Int32Array, u32: Uint32Array, f32: Float32Array }[lf.type];
		return new T(memory.buffer, base + lf.offset, layout.arrays[g].max);
	};

	const syncStatus = () => {
		const s = st();
		const f = layout.status.fields;
		s[f.in_stage] = state.playing ? 1 : 0;
		s[f.episode_id] = state.episode;
		s[f.last_frame] = state.lastObs;
		s[f.owner_state] = state.owner;
		s[f.owner_reason] = state.reason;
		s[f.owner_events] = state.events;
		s[f.observe] = state.observe ? 1 : 0;
	};

	const transition = (owner, reason) => {
		state.owner = owner;
		state.reason = reason;
		state.events++;
		state.slot = null;
		syncStatus();
		M.taiseiAIOnEvent?.(0, owner, reason);
	};

	M._taisei_ai_abi_version = () => options.abi ?? 1;
	M._taisei_ai_layout = () => jsonPtr;
	M._taisei_ai_layout_size = () => json.length;
	M._taisei_ai_set_observe = (v) => {
		state.observe = !!v;
		syncStatus();
	};
	M._taisei_ai_enable = () => {
		if (state.owner !== 0) return 2;
		if (!state.playing) {
			transition(2, 13);
			return 1;
		}
		transition(1, 6);
		return 0;
	};
	M._taisei_ai_resume = () => {
		if (state.owner !== 2) return 2;
		if (!state.playing) return 1;
		transition(1, 6);
		return 0;
	};
	M._taisei_ai_suspend = (r) => {
		if (state.owner === 1) transition(2, r);
	};
	M._taisei_ai_disable = (r) => {
		if (state.owner !== 0) transition(0, r);
	};
	M._taisei_ai_request_restart = () => {
		state.restarts++;
	};
	M._taisei_ai_set_seed = (lo, hi, sticky) => {
		state.seed = { lo: lo >>> 0, hi: hi >>> 0, sticky: !!sticky };
	};
	M._taisei_ai_clear_seed = () => {
		state.seed = null;
	};
	M._taisei_ai_submit = (ep, target, hold, edges) => {
		state.calls.push({ ep, target, hold, edges });
		if (state.owner !== 1) return 4;
		if (!state.playing) return 6;
		if (ep !== state.episode) return 3;
		if (target < state.lastObs + 1) return 1;
		if (target > state.lastObs + 1) return 5;
		if (state.slot) return 2;
		state.slot = { target, hold, edges };
		return 0;
	};

	// 테스트가 호출하는 가짜 게임 틱: 관측을 쓰고 동기 콜백을 부른 뒤 프레임을 올린다.
	M.__tick = (fill) => {
		const f = layout.i32.fields;
		const v = i32();
		state.lastObs = state.frame;
		v[f.schema_ver] = 1;
		v[f.frame] = state.frame;
		v[f.episode_id] = state.episode;
		v[f.owner_state] = state.owner;
		v[f.owner_reason] = state.reason;
		v[f.owner_events] = state.events;

		if (state.slot && state.slot.target === state.frame) {
			state.applied.push(state.slot);
			v[f.act_applied]++;
			v[f.hold_applied] = state.slot.hold;
			state.slot = null;
		}

		fill?.({
			i32: v,
			f32: f32(),
			fi: f,
			ff: layout.f32.fields,
			arr,
		});

		syncStatus();
		M.taiseiAIOnFrame?.(state.frame, state.episode);
		state.frame++;
	};

	M.__grow = (pages = 1) => memory.grow(pages);
	M.__state = state;
	M.__layout = layout;
	M.__arr = arr;
	M.__i32 = i32;
	M.__f32 = f32;

	syncStatus();
	void PAGE;
	return M;
}
