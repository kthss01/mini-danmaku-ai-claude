// 결정적 fixture 시나리오. 시드(mulberry32)와 정책 입력이 같으면 항상 같은 결과가 나온다.
// 실제 게임의 탄막이 아니라 직선탄·교차탄·레이저·벽·고속탄을 흉내 낸 합성 패턴이다.

import { mulberry32 } from './sim.js';

// 위에서 떨어지는 직선탄 비. 정지하면 곧 맞는다.
export function rain(seed = 1, { rate = 0.35, speed = 3.5, size = 12 } = {}) {
	const rnd = mulberry32(seed);
	return {
		name: 'rain',
		player: { x: 240, y: 496 },
		spawn(sim, frame) {
			if (frame % 3 === 0 || rnd() < rate) {
				const x = 8 + rnd() * 464;
				sim.addBullet({ x, y: -10, v: [0, speed], size: [size, size] });
			}
			if (rnd() < rate) {
				sim.addBullet({ x: 8 + rnd() * 464, y: -10, v: [0, speed * 0.8], size: [size, size] });
			}
		},
	};
}

// 좌우에서 비스듬히 들어와 서로 교차하는 탄
export function crossing(seed = 2) {
	const rnd = mulberry32(seed);
	return {
		name: 'crossing',
		player: { x: 240, y: 480 },
		spawn(sim, frame) {
			if (frame % 5 === 0) {
				const y = 300 + rnd() * 240;
				sim.addBullet({ x: -8, y, v: [3.2, -0.6 + rnd() * 1.2], size: [12, 12] });
			}
			if (frame % 5 === 2) {
				const y = 300 + rnd() * 240;
				sim.addBullet({ x: 488, y, v: [-3.2, -0.6 + rnd() * 1.2], size: [12, 12] });
			}
			if (frame % 17 === 0) {
				sim.addBullet({ x: 240 + (rnd() - 0.5) * 60, y: -8, v: [0, 3], size: [14, 14] });
			}
		},
	};
}

// 플레이어 아래쪽 열에 긴 세로 레이저가 충전된 뒤 켜진다. 폭은 원본 laser_charge를 따른다:
// 충전 단계(폭 ≤ 2) → 확장 단계(폭이 직선 증가) → 폭 > 목표 폭 × 0.6부터 충돌 활성.
// hideWidth: 관측에서 레이저 폭을 숨겨 활성 시점을 전혀 추정할 수 없게 한다.
export function verticalLaser({ x = 240, charge = 70, dur = 220, target = 24, hideWidth = false } = {}) {
	return {
		name: hideWidth ? 'laser-unknown-charge' : 'laser',
		player: { x, y: 496 },
		hideLaserWidth: hideWidth,
		init(sim) {
			sim.addLaser({
				ramp: { birth: 0, charge, dur, target },
				line: { a: { x, y: 0 }, b: { x, y: 560 } },
			});
		},
	};
}

// 가로 레이저가 위에서 아래로 내려온다(이동 형상). 가운데 틈(gapX 기준 ±gapHalf)이 있다.
// 정책은 직전 관측과의 끝점 차이로 선형 이동을 추정한다.
export function sweepingLaser({ speed = 2, gapX = 100, gapHalf = 30, giveHistory = true } = {}) {
	void giveHistory;
	return {
		name: 'sweeping-laser',
		player: { x: 380, y: 300 },
		init(sim) {
			sim.addLaser({
				update(frame) {
					const y = 20 + speed * frame;
					return [
						{ a: { x: -50, y }, b: { x: gapX - gapHalf, y }, wa: 14, wb: 14 },
						{ a: { x: gapX + gapHalf, y }, b: { x: 530, y }, wa: 14, wb: 14 },
					];
				},
				activateAt: 0, endAt: 400,
			});
		},
	};
}

// 구석에 몰린 상태에서 시작: 링 탄과 조준탄. 막다른 곳에 머무르면 맞는다
export function corner(seed = 3) {
	const rnd = mulberry32(seed);
	let rot = 0;
	return {
		name: 'corner',
		player: { x: 28, y: 524 },
		spawn(sim, frame) {
			if (frame % 36 === 1) {
				const n = 18;
				rot += 0.31;
				for (let k = 0; k < n; k++) {
					const a = rot + (k * 2 * Math.PI) / n;
					sim.addBullet({ x: 240, y: 200, v: [Math.cos(a) * 2.2, Math.sin(a) * 2.2], size: [10, 10] });
				}
			}
			if (frame % 7 === 0) {
				// 현재 플레이어 쪽으로 조준
				const dx = sim.player.x - 400;
				const dy = sim.player.y - 60;
				const d = Math.hypot(dx, dy) || 1;
				const j = (rnd() - 0.5) * 0.15;
				sim.addBullet({ x: 400, y: 60, v: [(dx / d) * 3.4 + j, (dy / d) * 3.4], size: [10, 10] });
			}
		},
	};
}

// 프레임 사이 이동량이 큰 고속탄이 플레이어의 가로 열을 가로지른다(터널링 판정)
export function fastCross(seed = 4) {
	const rnd = mulberry32(seed);
	return {
		name: 'fast-cross',
		player: { x: 240, y: 460 },
		spawn(sim, frame) {
			if (frame % 14 === 0) {
				const y = sim.player.y + (rnd() - 0.5) * 30;
				const dir = rnd() < 0.5 ? 1 : -1;
				sim.addBullet({ x: dir > 0 ? -20 : 500, y, v: [dir * 28, 0], size: [8, 8] });
			}
		},
	};
}

// 가속·감속하는 탄(retention, acceleration)과 곡선(인력)
export function accelerating(seed = 5) {
	const rnd = mulberry32(seed);
	return {
		name: 'accelerating',
		player: { x: 240, y: 480 },
		spawn(sim, frame) {
			if (frame % 6 === 0) {
				// 위에서 느리게 시작해 가속
				sim.addBullet({ x: 20 + rnd() * 440, y: -8, v: [0, 0.8], a: [0, 0.06], r: [1, 0], size: [12, 12] });
			}
			if (frame % 9 === 0) {
				// 빠르게 나와 감속
				sim.addBullet({ x: 20 + rnd() * 440, y: -8, v: [(rnd() - 0.5) * 2, 7], r: [0.96, 0], size: [12, 12] });
			}
			if (frame % 23 === 0) {
				// 플레이어 쪽으로 휘는 탄(인력)
				sim.addBullet({ x: rnd() * 480, y: -8, v: [0, 2.5], attr: [0.004, 0], ap: [sim.player.x, sim.player.y], exp: 1, size: [12, 12] });
			}
		},
	};
}

// 타원 탄(회전 포함): 길쭉한 탄이 비스듬히 내려온다
export function ellipses(seed = 6) {
	const rnd = mulberry32(seed);
	return {
		name: 'ellipses',
		player: { x: 240, y: 490 },
		spawn(sim, frame) {
			if (frame % 4 === 0) {
				const ang = (rnd() - 0.5) * 0.8;
				const sp = 3.4;
				const v = [Math.sin(ang) * sp, Math.cos(ang) * sp];
				// 탄이 진행 방향으로 길다: angle = 진행 방향(관측의 angle은 +π/2가 더해진다)
				sim.addBullet({ x: 20 + rnd() * 440, y: -12, v, size: [22, 8], angle: Math.atan2(v[1], v[0]) });
			}
		},
	};
}

// 관측에서 알 수 없는 방향 전환: 탄이 날아오다 task가 속도를 직접 바꿔 플레이어 쪽으로 꺾는다.
// MoveParams 전개는 변경 시점 이후 틀리므로 정책은 예측 실패를 겪는다(실패 사례를 따로 센다).
export function turning(seed = 9, { turnAfter = 28 } = {}) {
	const rnd = mulberry32(seed);
	return {
		name: 'turning',
		player: { x: 240, y: 490 },
		spawn(sim, frame) {
			if (frame % 8 === 0) {
				const x = 40 + rnd() * 400;
				sim.addBullet({
					x, y: -8, v: [0, 3.2], size: [10, 10],
					task(b, f, s) {
						if (b.age === turnAfter) {
							const dx = s.player.x - b.s.x;
							const dy = s.player.y - b.s.y;
							const d = Math.hypot(dx, dy) || 1;
							b.s.v = { x: (dx / d) * 3.6, y: (dy / d) * 3.6 }; // 규칙 밖의 순간적인 속도 변경
						}
					},
				});
			}
		},
	};
}

// 위에서 내려오는 가로 탄 벽에 빈 칸(틈)이 하나 있다. 틈은 직전 틈에서 gapShift 안쪽에 열려 도달 가능하다.
// 틈이 좁을수록 저속 이동이나 정지가 필요하다.
export function gapWall(seed = 7, { spacing = 24, size = 12, speed = 3, period = 48, gapShift = 110 } = {}) {
	const rnd = mulberry32(seed);
	let gapX = 380;
	return {
		name: 'gap-wall',
		player: { x: 240, y: 500 },
		spawn(sim, frame) {
			if (frame % period === 1) {
				gapX = Math.min(440, Math.max(40, gapX + (rnd() - 0.5) * 2 * gapShift));
				// 틈 = gapX에 가장 가까운 격자 칸 하나를 비운다
				const n = Math.floor(480 / spacing);
				const gapIdx = Math.round(gapX / spacing);

				for (let k = 1; k < n; k++) {
					if (k === gapIdx) {
						continue;
					}
					sim.addBullet({ x: k * spacing, y: -10, v: [0, speed], size: [size, size] });
				}
			}
		},
	};
}

export const ALL = {
	rain: () => rain(),
	crossing: () => crossing(),
	laser: () => verticalLaser(),
	'laser-unknown-charge': () => verticalLaser({ hideWidth: true }),
	corner: () => corner(),
	'fast-cross': () => fastCross(),
	accelerating: () => accelerating(),
	ellipses: () => ellipses(),
	'sweeping-laser': () => sweepingLaser(),
	'gap-wall': () => gapWall(),
	turning: () => turning(),
	'gap-wall-tight': () => gapWall(8, { spacing: 16, size: 12 }),
};
