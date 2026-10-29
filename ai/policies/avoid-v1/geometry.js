// 충돌 기하 함수. 원본 Taisei(`src/util/geometry.c`)의 식을 그대로 옮겼다.
// 좌표계: viewport 480x560, 원점 왼쪽 위, y는 아래로 증가.

export const VIEW_W = 480;
export const VIEW_H = 560;
export const MIN_BORDER = 16; // PLR_MIN_BORDER_DIST

// 원본 lineseg_closest_factor_impl: 선분 a→b 위에서 점 p에 가장 가까운 지점의 보간 계수
function closestFactor(ax, ay, bx, by, px, py) {
	const mx = bx - ax;
	const my = by - ay;
	const lm2 = mx * mx + my * my;

	if (lm2 === 0) {
		return 0;
	}

	const f = -((ax - px) * mx + (ay - py) * my) / lm2;
	return f < 0 ? 0 : f > 1 ? 1 : f;
}

// 선분 a→b에서 원점까지 최근접점의 거리 제곱.
// 원본 lineseg_circle_intersect_fallback의 `cabs2(p - c.origin)`과 같은 계산이다.
export function segOriginDist2(ax, ay, bx, by) {
	const f = closestFactor(ax, ay, bx, by, 0, 0);
	const x = ax + (bx - ax) * f;
	const y = ay + (by - ay) * f;
	return x * x + y * y;
}

// 원본 ucapsule_dist_from_point: 반지름이 양 끝에서 다른 캡슐 표면까지의 부호 있는 거리.
// 음수면 내부다. 원본과 같은 식이라 ra > rb인 입력도 원본과 같은 값을 낸다.
export function ucapsuleDist(px, py, ax, ay, bx, by, ra, rb) {
	px -= ax;
	py -= ay;
	bx -= ax;
	by -= ay;
	const h = bx * bx + by * by;
	let qx = (px * by - py * bx) / h;
	const qy = (px * bx + py * by) / h;
	qx = Math.abs(qx);

	const b = ra - rb;
	const cx = Math.sqrt(h - b * b);
	const cy = b;

	const k = cx * qy - cy * qx;
	const m = cx * qx + cy * qy;
	const n = qx * qx + qy * qy;

	if (k < 0) {
		return Math.sqrt(h * n) - ra;
	}

	if (k > cx) {
		return Math.sqrt(h * (n + 1 - 2 * qy)) - rb;
	}

	return m - ra;
}

// 원본 lineseg_lineseg_intersection(교차점 출력 없음).
// 평행·동일 직선은 교차로 보지 않는다.
export function segSegIntersect(p0x, p0y, p1x, p1y, p2x, p2y, p3x, p3y) {
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

// 플레이어가 한 프레임에 이동한 뒤의 위치(원본 player_move의 경계 고정 포함)
export function clampX(x) {
	return x < MIN_BORDER ? MIN_BORDER : x > VIEW_W - MIN_BORDER ? VIEW_W - MIN_BORDER : x;
}

export function clampY(y) {
	return y < MIN_BORDER ? MIN_BORDER : y > VIEW_H - MIN_BORDER ? VIEW_H - MIN_BORDER : y;
}
