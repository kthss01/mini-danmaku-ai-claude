// 관측 검증·해석. #21 `taisei.ai.obs/0` v0.2 필드 이름을 가정한다(계약 v1 전까지의 가정).
// 계약 v1이 필드 이름·단위를 바꾸면 이 파일만 고친다. 정책 본체는 validateObs가 돌려주는 값만 쓴다.
//
// obs (SoA): {
//   schema, frame, episode_id,
//   meta:    { overflow (비트 마스크, 0이면 완전한 관측) },
//   player:  { x, y, speed_normal, speed_focus, bombs, lives, phase,
//              deathtime, respawntime, recoverytime, bomb_endtime },
//   bullets: { n, id[], x[], y[], px[], py[], wx[], wy[], angle[],
//              (선택) vx[], vy[], ax[], ay[], retention_re[], retention_im[],
//                     attr_re[], attr_im[], attr_px[], attr_py[], attr_exp[], nomove[], age[] },
//   lasers:  { n, id[], active[], (선택) activate_in[] },   // activate_in: 활성까지 남은 프레임(알 때만)
//   laser_segs: { n, laser[] (laser 배열의 인덱스), ax[], ay[], bx[], by[], ra[], rb[] },
//   enemies: { n, x[], y[], hurt_radius[] },
// }
// 크기 wx, wy는 collision_size 그대로 **축 전체 길이(지름)**이고, angle은 타원 회전(p->angle + π/2)이다.

import { VIEW_W, VIEW_H } from './geometry.js';

export const SUPPORTED_OBS_SCHEMAS = ['taisei.ai.obs/0'];

const PHASES = ['normal', 'hit_pending', 'dead', 'recovering', 'bombing'];

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
	if (!SUPPORTED_OBS_SCHEMAS.includes(obs.schema)) {
		return fail('schema_mismatch', String(obs.schema));
	}
	if (!Number.isInteger(obs.frame) || obs.frame < 0) {
		return fail('bad_frame', String(obs.frame));
	}

	const p = obs.player;
	const b = obs.bullets;
	const meta = obs.meta || {};

	if (!p || !b) {
		return fail('missing_group', !p ? 'player' : 'bullets');
	}

	for (const key of ['x', 'y', 'speed_normal', 'speed_focus']) {
		if (!Number.isFinite(p[key])) {
			return fail('bad_player', key);
		}
	}
	if (p.x < -1 || p.x > VIEW_W + 1 || p.y < -1 || p.y > VIEW_H + 1) {
		// 사망 처리 중 화면 밖(dead)은 허용한다
		if (p.phase !== 'dead') {
			return fail('bad_player', 'position_out_of_range');
		}
	}
	if (!(p.speed_normal > 0) || !(p.speed_focus > 0) || p.speed_focus > p.speed_normal + 1e-9) {
		return fail('bad_player', 'speed');
	}
	if (!PHASES.includes(p.phase)) {
		return fail('bad_player', 'phase');
	}
	for (const key of ['deathtime', 'respawntime', 'recoverytime', 'bomb_endtime']) {
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

	const hasMove = arr(b, 'vx', b.n) !== null && arr(b, 'vy', b.n) !== null &&
		arr(b, 'ax', b.n) !== null && arr(b, 'ay', b.n) !== null &&
		arr(b, 'retention_re', b.n) !== null && arr(b, 'retention_im', b.n) !== null;

	if (hasMove) {
		for (const key of ['vx', 'vy', 'ax', 'ay', 'retention_re', 'retention_im']) {
			if (!allFinite(b[key], b.n)) {
				return fail('non_finite', `bullets.${key}`);
			}
		}
	}

	const hasAttr = hasMove && ['attr_re', 'attr_im', 'attr_px', 'attr_py', 'attr_exp'].every(k => arr(b, k, b.n) !== null);

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
	if (lasers.n > 0 && !arr(lasers, 'active', lasers.n)) {
		return fail('missing_field', 'lasers.active');
	}
	if (segs.n > 0 && !arr(segs, 'laser', segs.n)) {
		return fail('missing_field', 'laser_segs.laser');
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
		frame: obs.frame,
		episode: obs.episode_id === undefined ? 0 : obs.episode_id,
		overflow: Number.isFinite(meta.overflow) ? meta.overflow : 0,
		player: p,
		bossX: obs.boss && obs.boss.present && Number.isFinite(obs.boss.x) ? obs.boss.x : undefined,
		bullets: b,
		hasMove,
		hasAttr,
		hasAge: arr(b, 'age', b.n) !== null,
		hasId: arr(b, 'id', b.n) !== null,
		hasNomove: arr(b, 'nomove', b.n) !== null,
		lasers,
		segs,
		enemies,
	};
}
