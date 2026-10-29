// fixture 비교 표 생성(실제 게임 결과가 아니다):
//   node tests/ai-policy/report.mjs [프레임 수=1800] [시드 수=5]
// 같은 시나리오·같은 시드에서 idle, simple-move, avoid-v1을 돌려 생존·피격·봄·판단 시간을 표로 낸다.
import * as avoid from '../../ai/policies/avoid-v1/index.js';
import * as idle from '../../ai/policies/idle/index.js';
import * as simple from '../../ai/policies/simple-move/index.js';
import * as sc from './scenarios.js';
import { runEpisode } from './sim.js';

const FRAMES = Number(process.argv[2] || 1800);
const SEEDS = Number(process.argv[3] || 5);

const CASES = [
	['직선탄(비)', s => sc.rain(s)],
	['직선탄(비, 고밀도)', s => sc.rain(s, { rate: 1.5 })],
	['교차탄', s => sc.crossing(s)],
	['가속·감속·곡선 탄', s => sc.accelerating(s)],
	['타원 탄', s => sc.ellipses(s)],
	['고속탄(프레임 사이 통과)', s => sc.fastCross(s)],
	['구석에서 시작(벽)', s => sc.corner(s)],
	['좁은 틈 벽', s => sc.gapWall(s, { spacing: 16 })],
	['규칙 밖 속도 변경 탄', s => sc.turning(s)],
	['세로 레이저(충전→활성)', () => sc.verticalLaser()],
	['이동 레이저(틈 있음)', () => sc.sweepingLaser()],
];

const POLICIES = [['idle', idle], ['simple-move', simple], ['avoid-v1', avoid]];

function mean(a) {
	return a.reduce((x, y) => x + y, 0) / a.length;
}

console.log(`fixture 비교 (합성 탄막, 실제 게임 아님) — 프레임 ${FRAMES}, 시드 ${SEEDS}개\n`);
console.log('| 시나리오 | 정책 | 무피격 완주 | 평균 생존 프레임 | 입력 해제 프레임 | 봄 | 판단 p50 / p95 / max (ms) |');
console.log('| --- | --- | --- | --- | --- | --- | --- |');

for (const [label, make] of CASES) {
	for (const [pname, mod] of POLICIES) {
		const runs = [];

		for (let seed = 1; seed <= SEEDS; seed++) {
			const policy = mod.init({}, { now: () => performance.now() });
			const r = runEpisode({ policy, scenario: make(seed), frames: FRAMES });
			runs.push({ r, stats: policy.stats() });
		}

		const ok = runs.filter(x => x.r.survived).length;
		const bombs = runs.reduce((a, x) => a + (x.stats.bombs ? x.stats.bombs.length : 0), 0);
		const rel = runs.reduce((a, x) => a + x.r.released_frames, 0);
		const p50 = mean(runs.map(x => x.r.decision_ms.p50));
		const p95 = mean(runs.map(x => x.r.decision_ms.p95));
		const max = Math.max(...runs.map(x => x.r.decision_ms.max));
		console.log(`| ${label} | ${pname} | ${ok}/${SEEDS} | ${mean(runs.map(x => x.r.survived_frames)).toFixed(0)} | ${rel} | ${bombs} | ${p50.toFixed(2)} / ${p95.toFixed(2)} / ${max.toFixed(2)} |`);
	}
}
