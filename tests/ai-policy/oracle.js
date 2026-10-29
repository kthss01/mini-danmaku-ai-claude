// 원본 Taisei 판정 코드의 **직역 포트**(회귀 테스트용 기준).
// 정책 구현(ai/policies/avoid-v1/geometry.js, scene.js)은 이 파일과 독립적으로 쓰였고,
// 테스트는 같은 입력에서 두 구현의 결과가 같은지 비교한다.
// 근거(fork f59212b7 기준, game/taisei/src):
//   util/geometry.c lineseg_ellipse_intersect / lineseg_circle_intersect(+_fallback) / ucapsule_dist_from_point /
//                   lineseg_lineseg_intersection / rect_rect_intersect
//   projectile.c calc_projectile_collision, lasers/laser.c laser_collision, enemy.c, move.c move_update,
//   player.c player_move
// 복소수는 {x, y} 쌍으로 쓴다(원본 re = x, im = y).

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

export function rectRectIntersect(r1, r2) {
	// 원본 rect_rect_intersect(edges=true, corners=true): 경계가 닿으면 교차
	return !(r1.bottom < r2.top || r1.top > r2.bottom || r1.left > r2.right || r1.right < r2.left);
}

export function linesegBbox(seg) {
	return {
		left: Math.min(seg.a.x, seg.b.x),
		right: Math.max(seg.a.x, seg.b.x),
		top: Math.min(seg.a.y, seg.b.y),
		bottom: Math.max(seg.a.y, seg.b.y),
	};
}

function circleBbox(origin, radius) {
	return { left: origin.x - radius, right: origin.x + radius, top: origin.y - radius, bottom: origin.y + radius };
}

function linesegClosestFactor(seg, p) {
	const mx = seg.b.x - seg.a.x;
	const my = seg.b.y - seg.a.y;
	const lm2 = mx * mx + my * my;

	if (lm2 === 0) {
		return 0;
	}

	// v = a − p, f = −re(v · conj(m)) / |m|²
	const vx = seg.a.x - p.x;
	const vy = seg.a.y - p.y;
	return clamp(-(vx * mx + vy * my) / lm2, 0, 1);
}

function circleFallback(seg, origin, radius) {
	const rad2 = radius * radius;
	const f = linesegClosestFactor(seg, origin);
	const px = seg.a.x + (seg.b.x - seg.a.x) * f;
	const py = seg.a.y + (seg.b.y - seg.a.y) * f;
	const dx = px - origin.x;
	const dy = py - origin.y;
	return dx * dx + dy * dy <= rad2 ? f : -1;
}

function linesegCircleIntersect(seg, origin, radius) {
	if (rectRectIntersect(linesegBbox(seg), circleBbox(origin, radius))) {
		return circleFallback(seg, origin, radius) >= 0;
	}
	return false;
}

// axes는 [x축 전체 길이, y축 전체 길이](지름), angle은 Ellipse.angle
export function linesegEllipseIntersect(seg, origin, axes, angle) {
	if (axes[0] === axes[1]) {
		return linesegCircleIntersect(seg, origin, axes[0] * 0.5);
	}

	const eBbox = circleBbox(origin, Math.max(axes[0], axes[1]) * 0.5);

	if (!rectRectIntersect(linesegBbox(seg), eBbox)) {
		return false;
	}

	let a = { x: seg.a.x - origin.x, y: seg.a.y - origin.y };
	let b = { x: seg.b.x - origin.x, y: seg.b.y - origin.y };
	const ratio = axes[0] / axes[1];

	if (ratio !== ratio || !ratio) {
		return false;
	}

	const rc = Math.cos(-angle);
	const rs = Math.sin(-angle);
	a = { x: a.x * rc - a.y * rs, y: a.x * rs + a.y * rc };
	b = { x: b.x * rc - b.y * rs, y: b.x * rs + b.y * rc };
	a.y *= ratio;
	b.y *= ratio;

	return circleFallback({ a, b }, { x: 0, y: 0 }, axes[0] * 0.5) >= 0;
}

// 원본 calc_projectile_collision (PROJ_ENEMY 분기, 피격 판정만)
// p: { pos, prevpos, size: [wx, wy], angle }  (angle은 p->angle, 타원 회전은 +π/2)
export function projectileHitsPlayer(p, plrPos, plrVel) {
	const seg = {
		a: { x: plrPos.x - plrVel.x - p.prevpos.x, y: plrPos.y - plrVel.y - p.prevpos.y },
		b: { x: plrPos.x - p.pos.x, y: plrPos.y - p.pos.y },
	};

	return linesegEllipseIntersect(seg, { x: 0, y: 0 }, p.size, p.angle + Math.PI / 2);
}

export function linesegLinesegIntersection(s0, s1) {
	const p0x = s0.a.x, p0y = s0.a.y, p1x = s0.b.x, p1y = s0.b.y;
	const p2x = s1.a.x, p2y = s1.a.y, p3x = s1.b.x, p3y = s1.b.y;
	const s1x = p1x - p0x;
	const s1y = p1y - p0y;
	const s2x = p3x - p2x;
	const s2y = p3y - p2y;
	const d = -s2x * s1y + s1x * s2y;

	if (d === 0) {
		return false;
	}

	const s = (-s1y * (p0x - p2x) + s1x * (p0y - p2y)) / d;

	if (s < 0 || s > 1) {
		return false;
	}

	const t = (s2x * (p0y - p2y) - s2y * (p0x - p2x)) / d;
	return !(t < 0 || t > 1);
}

// 원본 ucapsule_dist_from_point. 복소수 연산을 그대로 풀어 썼다.
export function ucapsuleDistFromPoint(p, cap) {
	const pp = { x: p.x - cap.a.x, y: p.y - cap.a.y };
	const b2 = { x: cap.b.x - cap.a.x, y: cap.b.y - cap.a.y };
	const h = b2.x * b2.x + b2.y * b2.y;
	// cswap(b) = (b.y, b.x), conj → (b.y, −b.x)
	const cs = { x: b2.y, y: -b2.x };
	let q = { x: (pp.x * cs.x + pp.y * cs.y) / h, y: (pp.x * b2.x + pp.y * b2.y) / h };
	q = { x: Math.abs(q.x), y: q.y };

	const b = cap.ra - cap.rb;
	const c = { x: Math.sqrt(h - b * b), y: b };
	const k = c.x * q.y - c.y * q.x; // ccross(c, q)
	const m = c.x * q.x + c.y * q.y; // cdot(c, q)
	const n = q.x * q.x + q.y * q.y;

	if (k < 0) {
		return Math.sqrt(h * n) - cap.ra;
	}
	if (k > c.x) {
		return Math.sqrt(h * (n + 1 - 2 * q.y)) - cap.rb;
	}
	return m - cap.ra;
}

// 원본 laser_collision (graze 제외). segs: [{a, b, wa, wb}] — 폭은 LaserSegment.width, 반지름 = max(w/2 − 4, 2)
// bboxMargin: 원본이 레이저 전체 bbox에 더하는 여유(LASER_SDF_RANGE + width/2)
export function laserHitsPlayer(segs, plrPos, plrVel, bboxMargin, active = true) {
	if (!active || segs.length < 1) {
		return false;
	}

	// 레이저 전체 bbox (laser.c: 세그먼트 끝점의 bbox + margin)
	let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;

	for (const s of segs) {
		left = Math.min(left, s.a.x, s.b.x);
		top = Math.min(top, s.a.y, s.b.y);
		right = Math.max(right, s.a.x, s.b.x);
		bottom = Math.max(bottom, s.a.y, s.b.y);
	}

	left -= bboxMargin;
	top -= bboxMargin;
	right += bboxMargin;
	bottom += bboxMargin;

	if (!(plrPos.x >= left && plrPos.x <= right && plrPos.y >= top && plrPos.y <= bottom)) {
		return false;
	}

	const moved = plrVel.x !== 0 || plrVel.y !== 0;
	const motion = { a: moved ? { x: plrPos.x - plrVel.x, y: plrPos.y - plrVel.y } : plrPos, b: plrPos };
	const mbox = linesegBbox(motion);

	for (const s of segs) {
		const cap = {
			a: s.a, b: s.b,
			ra: Math.max(s.wa * 0.5 - 4, 2),
			rb: Math.max(s.wb * 0.5 - 4, 2),
		};
		const sbox = {
			left: Math.min(cap.a.x - cap.ra, cap.b.x - cap.rb),
			right: Math.max(cap.a.x + cap.ra, cap.b.x + cap.rb),
			top: Math.min(cap.a.y - cap.ra, cap.b.y - cap.rb),
			bottom: Math.max(cap.a.y + cap.ra, cap.b.y + cap.rb),
		};

		if (!rectRectIntersect(mbox, sbox)) {
			continue;
		}
		if (moved && linesegLinesegIntersection(motion, { a: s.a, b: s.b })) {
			return true;
		}
		if (ucapsuleDistFromPoint(plrPos, cap) < 0) {
			return true;
		}
	}

	return false;
}

// 적 접촉(enemy.c): 중심 거리 < hurt_radius (경계 미포함)
export function enemyTouchesPlayer(enemyPos, hurtRadius, plrPos) {
	const dx = enemyPos.x - plrPos.x;
	const dy = enemyPos.y - plrPos.y;
	return Math.sqrt(dx * dx + dy * dy) < hurtRadius;
}

// 원본 move_update. state: { x, y, v:{x,y}, a:{x,y}, r:{x,y}, attr:{x,y}, ap:{x,y}, exp }
export function moveUpdate(s) {
	const ov = { x: s.v.x, y: s.v.y };
	s.x += ov.x;
	s.y += ov.y;
	let nv = { x: s.a.x + s.r.x * ov.x - s.r.y * ov.y, y: s.a.y + s.r.x * ov.y + s.r.y * ov.x };

	if (s.attr && (s.attr.x !== 0 || s.attr.y !== 0)) {
		const av = { x: s.ap.x - s.x, y: s.ap.y - s.y };

		if (s.exp === 1) {
			nv = { x: nv.x + s.attr.x * av.x - s.attr.y * av.y, y: nv.y + s.attr.x * av.y + s.attr.y * av.x };
		} else if (av.x !== 0 || av.y !== 0) {
			const m = Math.pow(av.x * av.x + av.y * av.y, 0.5 * s.exp - 0.5);
			const w = { x: av.x * m, y: av.y * m };
			nv = { x: nv.x + s.attr.x * w.x - s.attr.y * w.y, y: nv.y + s.attr.x * w.y + s.attr.y * w.x };
		}
	}

	s.v = nv;
	return ov;
}

// 원본 player_move: 방향 단위벡터 × 속도, 경계에서 16 이상 떨어지도록 고정
export function playerMove(pos, dir, speed, viewW = 480, viewH = 560, border = 16) {
	const x = clamp(pos.x + dir.x * speed, border, viewW - border);
	const y = clamp(pos.y + dir.y * speed, border, viewH - border);
	return { pos: { x, y }, vel: { x: x - pos.x, y: y - pos.y } };
}
