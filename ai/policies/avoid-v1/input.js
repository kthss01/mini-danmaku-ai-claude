// 관측 검증·해석. 계약 `taisei.ai.obs/1`(docs/ai/CONTRACT.md, PR #39)의 JS 어댑터 형태를 받는다.
// 어댑터 `ai/bridge/taisei-ai-bridge.mjs`의 read()가 돌려주는 객체와 같다. 계약이 바뀌면 이 파일만 고친다.
//
// obs: {
//   meta:    { schema_ver (=1), frame, episode_id, overflow (비트 마스크, 0이면 완전한 관측), … },
//   player:  { x, y, vx, vy, speed_normal, speed_focus, bombs, lives, phase (정수 0..4),
//              deathtime, respawntime, recoverytime, bomb_endtime, … },
//   boss:    { present, x, y, … },
//   bullets: { n, id[], x[], y[], px[], py[], wx[], wy[], angle[],
//              vx[], vy[], ax[], ay[], ret_re[], ret_im[], attr_re[], attr_im[], attr_x[], attr_y[], attr_exp[],
//              flags[] (비트 0 = NOMOVE), age[] },
//   lasers:  { n, id[], active[], width[], seg_start[], seg_count[], … },
//   laser_segs: { n, ax[], ay[], bx[], by[], ra[], rb[] },
//   enemies: { n, x[], y[], hurt_radius[], … },
// }
// 크기 wx, wy는 collision_size 그대로 **축 전체 길이(지름)**이고, angle은 타원 회전(p->angle + π/2)이다.
// 이동 규칙(vx…attr_exp)이 없는 관측도 받는다(직선 외삽으로 대체).

import { VIEW_W, VIEW_H } from './geometry.js';

export const SUPPORTED_OBS_VERSIONS = [1];
export const OBS_SCHEMA_NAME = 'taisei.ai.obs/1';

export const PHASES = ['normal', 'hit_pending', 'dead', 'recovering', 'bombing'];

function fail(reason, detail) {
	return { ok: false, reason, detail };
}

function isCount(n, max) {
	return Number.isInteger(n) && n >= 0 && n <= max;
}

function arr(group, name, n) {
	const a = group[name];
	return a !== undefined && a !== null && typeof a.length === 'number' && a.length >= n ? a : null;
}

// 모든 요소가 유한한 수인지 확인한다(O(n), 4096개 기준 수십 µs)
function allFinite(a, n) {
	for (let i = 0; i < n; i++) {
		if (!Number.isFinite(a[i])) {
			return false;
		}
	}
	return true;
}

export function validateObs(obs) {
	if (obs === null || typeof obs !== 'object') {
		return fail('missing_observation');
	}
	const meta = obs.meta;

	if (!meta || typeof meta !== 'object') {
		return fail('missing_group', 'meta');
	}
	if (!SUPPORTED_OBS_VERSIONS.includes(meta.schema_ver)) {
		return fail('schema_mismatch', String(meta.schema_ver));
	}
	if (!Number.isInteger(meta.frame) || meta.frame < 0) {
		return fail('bad_frame', String(meta.frame));
	}

	const p = obs.player;
	const b = obs.bullets;

	if (!p || !b) {
		return fail('missing_group', !p ? 'player' : 'bullets');
	}

	for (const key of ['x', 'y', 'speed_normal', 'speed_focus']) {
		if (!Number.isFinite(p[key])) {
			return fail('bad_player', key);
		}
	}
	const phase = PHASES[p.phase];

	if (phase === undefined) {
		return fail('bad_player', 'phase');
	}
	if (p.x < -1 || p.x > VIEW_W + 1 || p.y < -1 || p.y > VIEW_H + 1) {
		// 사망 처리 중 화면 밖(dead)은 허용한다
		if (phase !== 'dead') {
			return fail('bad_player', 'position_out_of_range');
		}
	}
	if (!(p.speed_normal > 0) || !(p.speed_focus > 0) || p.speed_focus > p.speed_normal + 1e-9) {
		return fail('bad_player', 'speed');
	}
	for (const key of ['bombs', 'deathtime', 'respawntime', 'recoverytime', 'bomb_endtime']) {
		if (!Number.isFinite(p[key])) {
			return fail('bad_player', key);
		}
	}

	if (!isCount(b.n, 1 << 16)) {
		return fail('bad_count', 'bullets.n');
	}
	for (const key of ['x', 'y', 'px', 'py', 'wx', 'wy', 'angle']) {
		const a = arr(b, key, b.n);
		if (!a) {
			return fail('missing_field', `bullets.${key}`);
		}
		if (!allFinite(a, b.n)) {
			return fail('non_finite', `bullets.${key}`);
		}
	}

	// 탄 크기(지름)는 음수일 수 없다. 0은 충돌 형상이 없는 탄이라 위험 목록에서 빼고 보수 동작으로 표시한다.
	let degenerate = 0;

	for (let i = 0; i < b.n; i++) {
		if (b.wx[i] < 0 || b.wy[i] < 0) {
			return fail('bad_size', `bullets[${i}]`);
		}
		if (b.wx[i] === 0 || b.wy[i] === 0) {
			degenerate++;
		}
	}

	const hasMove = arr(b, 'vx', b.n) !== null && arr(b, 'vy', b.n) !== null &&
		arr(b, 'ax', b.n) !== null && arr(b, 'ay', b.n) !== null &&
		arr(b, 'ret_re', b.n) !== null && arr(b, 'ret_im', b.n) !== null;

	if (hasMove) {
		for (const key of ['vx', 'vy', 'ax', 'ay', 'ret_re', 'ret_im']) {
			if (!allFinite(b[key], b.n)) {
				return fail('non_finite', `bullets.${key}`);
			}
		}
	}

	const hasAttr = hasMove && ['attr_re', 'attr_im', 'attr_x', 'attr_y', 'attr_exp'].every(k => arr(b, k, b.n) !== null);

	if (hasAttr) {
		for (const key of ['attr_re', 'attr_im', 'attr_x', 'attr_y', 'attr_exp']) {
			if (!allFinite(b[key], b.n)) {
				return fail('non_finite', `bullets.${key}`);
			}
		}
	}

	const lasers = obs.lasers || { n: 0 };
	const segs = obs.laser_segs || { n: 0 };
	const enemies = obs.enemies || { n: 0 };

	if (!isCount(lasers.n, 4096) || !isCount(segs.n, 1 << 16) || !isCount(enemies.n, 4096)) {
		return fail('bad_count', 'lasers/laser_segs/enemies');
	}
	for (const key of ['ax', 'ay', 'bx', 'by', 'ra', 'rb']) {
		if (segs.n > 0) {
			const a = arr(segs, key, segs.n);
			if (!a) {
				return fail('missing_field', `laser_segs.${key}`);
			}
			if (!allFinite(a, segs.n)) {
				return fail('non_finite', `laser_segs.${key}`);
			}
		}
	}
	if (lasers.n > 0) {
		for (const key of ['active', 'seg_start', 'seg_count']) {
			if (!arr(lasers, key, lasers.n)) {
				return fail('missing_field', `lasers.${key}`);
			}
		}
		for (let i = 0; i < lasers.n; i++) {
			const st = lasers.seg_start[i];
			const ct = lasers.seg_count[i];

			if (!Number.isInteger(st) || !Number.isInteger(ct) || st < 0 || ct < 0 || st + ct > segs.n) {
				return fail('bad_count', 'lasers.seg_start/seg_count');
			}
		}
		if (lasers.width !== undefined && lasers.width !== null && !allFinite(lasers.width, lasers.n)) {
			return fail('non_finite', 'lasers.width');
		}
	}
	if (enemies.n > 0) {
		for (const key of ['x', 'y', 'hurt_radius']) {
			const a = arr(enemies, key, enemies.n);
			if (!a) {
				return fail('missing_field', `enemies.${key}`);
			}
			if (!allFinite(a, enemies.n)) {
				return fail('non_finite', `enemies.${key}`);
			}
		}
	}

	return {
		ok: true,
		frame: meta.frame,
		episode: meta.episode_id === undefined ? 0 : meta.episode_id,
		overflow: Number.isFinite(meta.overflow) ? meta.overflow : 0,
		player: p,
		phase,
		bossX: obs.boss && obs.boss.present && Number.isFinite(obs.boss.x) ? obs.boss.x : undefined,
		bullets: b,
		hasMove,
		hasAttr,
		degenerate,
		hasAge: arr(b, 'age', b.n) !== null,
		hasId: arr(b, 'id', b.n) !== null,
		hasFlags: arr(b, 'flags', b.n) !== null,
		lasers,
		segs,
		enemies,
	};
}
