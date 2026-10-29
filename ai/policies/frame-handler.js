// 정책 → 브리지 어댑터 연결 도우미. 정책 번들(`taisei.ai.policy/0`)의 action을
// 브리지 계약 v1의 `bridge.onFrame((obs, ctl) => …)` 콜백으로 옮긴다.
//
//   const policy = (await import('/ai/policies/avoid-v1/index.js')).init({}, { now: () => performance.now() });
//   bridge.onFrame(createFrameHandler(policy, { bridge }));
//
// 규칙
// - 정상 action은 `ctl.submit({ hold, edges })`로 그대로 제출한다.
// - `request.type === 'release'`: 이번 프레임 입력을 모두 해제한다(`hold = 0, edges = 0` 제출).
//   소유권은 유지한다. 생존 보장이 아니라 제어 중단이다.
// - `request.type === 'suspend'`: 입력을 해제하고 `bridge.suspend(reason)`로 `ai_suspended`로 올린다.
// - 정책이 예외를 던지면 잡지 않는다. 어댑터가 `disable('policy_error')`로 처리한다(CONTRACT 6.3절).
// - 결과 요약(모드, 판단 시간, 요청)은 `onDecision(action, ms)`로 알린다.

export function createFrameHandler(policy, { bridge, now, onDecision } = {}) {
	const clock = typeof now === 'function' ? now : () => performance.now();

	return function onFrame(obs, ctl) {
		const t0 = clock();
		const action = policy.decide(obs);
		const ms = clock() - t0;

		if (action.request) {
			ctl.submit({ hold: 0, edges: 0 });

			if (action.request.type === 'suspend' && bridge) {
				bridge.suspend(action.request.reason);
			}
		} else {
			ctl.submit({ hold: action.hold, edges: action.edges });
		}

		if (onDecision) {
			onDecision(action, ms);
		}

		return action;
	};
}
