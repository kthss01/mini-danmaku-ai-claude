/*
 * Taisei 웹 셸의 AI 호스트 API (window.taiseiAI).
 *
 * 역할: 수동/AI 소유권 전환, 정책 구동, 상태·오류 노출을 한 경로로 모은다.
 * 셸 UI(shell.js)와 실행기(세션 1, Playwright)가 같은 API를 쓴다.
 * 소유권의 진실은 브리지(세션 2, ai/bridge/taisei-ai-bridge.mjs)의 owner_state다. 이 파일은 그 위에서
 *   - 어댑터가 없을 때의 안전한 기본 동작(unavailable)
 *   - 정책 번들(세션 3, taisei.ai.policy/0)을 프레임 콜백에 연결
 *   - 포커스 상실·정책 오류 같은 호스트 사유 전달
 *   - UI·평가가 같은 사유 코드 문자열을 쓰도록 사유 설명 제공
 * 만 맡는다. 게임 규칙·판정·입력 경로는 건드리지 않는다.
 *
 * 어댑터(브리지) 계약: docs/ai/CONTRACT.md 10절. 이 파일은 아래 메서드만 쓴다.
 *   enable() resume() suspend(reason) disable(reason) state() onEvent(cb) onFrame(cb) setObserve(on)
 * 검증용 mock 어댑터는 tests/ai-integration/mock-adapter.js 에 있다(실제 게임 결과가 아니다).
 *
 * 브라우저에서는 전역 window.taiseiAI(createHost()의 결과)와 window.taiseiAIHost(팩토리)를 정의하고,
 * Node 테스트에서는 require()로 팩토리를 받는다.
 */
(function (root, factory) {
    'use strict';
    var api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    } else {
        root.taiseiAIHost = api;
        root.taiseiAI = api.createHost();
    }
})(typeof window !== 'undefined' ? window : this, function () {
    'use strict';

    var HOST_SCHEMA = 'taisei.ai.host/0';

    // CONTRACT.md 4.2절 사유 코드. 문자열은 UI·owner_state 전환·평가 run.reason_code가 같다.
    // kind: info(정상 경계) | warn(사용자 조치 필요) | error(실패)
    var REASON_INFO = {
        none: { kind: 'info', text: '' },
        pause: { kind: 'warn', text: '게임이 일시정지되어 AI를 멈췄습니다. 재개를 눌러야 다시 시작합니다.' },
        focus_lost: { kind: 'warn', text: '창 포커스를 잃어 AI를 멈췄습니다. 게임 화면을 클릭한 뒤 재개를 눌러 주세요.' },
        dialog: { kind: 'info', text: '대화 구간에서 AI를 멈췄습니다.' },
        stage_end: { kind: 'info', text: '스테이지가 끝나 AI를 멈췄습니다.' },
        restart: { kind: 'info', text: '재시작으로 AI를 멈췄습니다.' },
        host_request: { kind: 'info', text: '사용자 요청으로 전환했습니다.' },
        user_input: { kind: 'warn', text: '사용자 키 입력으로 수동 모드로 바뀌었습니다. 입력은 섞지 않습니다.' },
        policy_error: { kind: 'error', text: '정책에서 오류가 나 수동 모드로 바뀌었습니다.' },
        policy_deadline: { kind: 'error', text: '정책 판단 시간이 초과되어 멈췄습니다.' },
        observation_invalid: { kind: 'error', text: '관측이 올바르지 않아 수동 모드로 바뀌었습니다.' },
        bridge_error: { kind: 'error', text: '브리지 오류로 수동 모드로 바뀌었습니다.' },
        game_over: { kind: 'info', text: '게임 오버(컨티뉴 화면)로 AI를 멈췄습니다. 컨티뉴를 쓰면 클리어로 인정하지 않습니다.' },
        not_playing: { kind: 'warn', text: '진행 중인 스테이지가 아니라서 시작하지 못했습니다. 스테이지에 들어간 뒤 재개를 눌러 주세요.' },
    };

    // 호스트가 adapter.suspend/disable에 넘길 수 있는 사유. 브리지 자동 사유(pause, stage_end 등)는 호스트가 만들지 않는다.
    var HOST_REASONS = ['focus_lost', 'dialog', 'host_request', 'policy_error', 'policy_deadline', 'observation_invalid'];

    var STATS_RING = 512;
    var FRAME_BUDGET_MS = 1000 / 60;

    function percentile(sorted, q) {
        if (!sorted.length) return null;
        var i = Math.min(sorted.length - 1, Math.max(0, Math.ceil(q * sorted.length) - 1));
        return sorted[i];
    }

    function reasonInfo(reason) {
        return REASON_INFO[reason] || { kind: 'info', text: String(reason || '') };
    }

    function createHost(options) {
        options = options || {};
        var now = options.now || function () {
            return typeof performance !== 'undefined' ? performance.now() : Date.now();
        };

        var adapter = null;
        var adapterKind = null;      // 'real' | 'mock'
        var unavailableReason = options.unavailableReason || '브리지가 연결되지 않았습니다.';
        var listeners = [];
        var lastError = null;
        var build = { flavor: 'unknown', taiseiCommit: null, source: null };

        // 정책: 객체(직접 전달) 또는 {module, config}(호스트가 init/dispose를 관리)
        var policy = null;           // 현재 쓰는 정책 인스턴스 {decide, reset?, dispose?, stats?, describe?}
        var policySource = null;     // {kind:'object', obj} | {kind:'module', mod, config, url}
        var policyInfo = null;       // {id, version, url?}
        var ownsPolicy = false;      // 호스트가 init했으면 dispose도 호스트가 한다
        var lastEpisode = null;

        // 셸의 AI 초기화(브리지·빌드 정보·정책 불러오기)가 끝나면 settle된다. 실행기는 이 Promise를 기다린 뒤 enable한다.
        var readyResolve;
        var readyPromise = new Promise(function (resolve) { readyResolve = resolve; });

        var stats = { count: 0, over_frame: 0, total_ms: 0, max_ms: 0, ring: [], ringPos: 0, actions: 0, releases: 0, policy_suspends: 0 };

        function emit(event) {
            event.at = Date.now();
            for (var i = 0; i < listeners.length; i++) {
                try { listeners[i](event); } catch (e) { /* 구독자 오류가 호스트를 멈추지 않게 한다 */ }
            }
        }

        function setError(code, message) {
            lastError = { code: code, message: message, at: Date.now() };
            emit({ type: 'error', code: code, message: message });
        }

        function recordDecision(ms) {
            stats.count++;
            stats.total_ms += ms;
            if (ms > stats.max_ms) stats.max_ms = ms;
            if (ms > FRAME_BUDGET_MS) stats.over_frame++;
            if (stats.ring.length < STATS_RING) {
                stats.ring.push(ms);
            } else {
                stats.ring[stats.ringPos] = ms;
                stats.ringPos = (stats.ringPos + 1) % STATS_RING;
            }
        }

        function resetStats() {
            stats = { count: 0, over_frame: 0, total_ms: 0, max_ms: 0, ring: [], ringPos: 0, actions: 0, releases: 0, policy_suspends: 0 };
        }

        function decisionStats() {
            var sorted = stats.ring.slice().sort(function (a, b) { return a - b; });
            return {
                count: stats.count,
                p50_ms: percentile(sorted, 0.5),
                p95_ms: percentile(sorted, 0.95),
                max_ms: stats.count ? stats.max_ms : null,
                mean_ms: stats.count ? stats.total_ms / stats.count : null,
                over_frame: stats.over_frame,
                frame_budget_ms: FRAME_BUDGET_MS,
                actions: stats.actions,
                releases: stats.releases,
                policy_suspends: stats.policy_suspends,
            };
        }

        // ---------- 정책 구동 ----------
        function disposePolicy() {
            if (policy && ownsPolicy && typeof policy.dispose === 'function') {
                try { policy.dispose(); } catch (e) { /* 정리 중 오류는 무시 */ }
            }
            if (policySource && policySource.kind === 'module') policy = null;
            ownsPolicy = false;
        }

        function ensurePolicyInstance() {
            if (policy) return true;
            if (!policySource) return false;
            if (policySource.kind === 'object') {
                policy = policySource.obj;
                ownsPolicy = false;
                return true;
            }
            try {
                policy = policySource.mod.init(policySource.config || {}, { now: now });
                ownsPolicy = true;
                return true;
            } catch (e) {
                policy = null;
                setError('policy_error', '정책 초기화 실패: ' + (e && e.message ? e.message : e));
                return false;
            }
        }

        function resetPolicy(why) {
            if (policy && typeof policy.reset === 'function') {
                try { policy.reset(why); } catch (e) { /* reset 오류는 다음 decide에서 드러난다 */ }
            }
        }

        function submitAction(ctl, act) {
            var edges = (act.bomb ? 1 : 0) | (act.special ? 2 : 0);
            ctl.submit({ hold: act.hold | 0, edges: edges });
            stats.actions++;
        }

        // 브리지 동기 콜백. 캡처 직후 같은 틱 안에서 불리므로 정책 시간이 곧 프레임 시간에 포함된다.
        function frameDriver(obs, ctl) {
            if (!policy || !obs || !obs.meta || obs.meta.owner !== 'ai_active') return;
            if (lastEpisode !== obs.meta.episode_id) {
                if (lastEpisode !== null) resetPolicy('episode');
                lastEpisode = obs.meta.episode_id;
            }
            var act;
            var t0 = now();
            try {
                act = policy.decide(obs);
            } catch (e) {
                setError('policy_error', '정책 decide 예외: ' + (e && e.message ? e.message : e));
                safeCall(function () { adapter.disable('policy_error'); });
                return;
            }
            recordDecision(now() - t0);
            if (!act || typeof act !== 'object') {
                setError('policy_error', '정책이 올바르지 않은 액션을 돌려주었습니다.');
                safeCall(function () { adapter.disable('policy_error'); });
                return;
            }
            var req = act.request;
            if (req && req.type === 'suspend') {
                stats.policy_suspends++;
                var reason = HOST_REASONS.indexOf(req.reason) !== -1 ? req.reason : 'policy_deadline';
                submitAction(ctl, { hold: 0 });
                safeCall(function () { adapter.suspend(reason); });
                return;
            }
            if (req && req.type === 'release') {
                stats.releases++;
                ctl.submit({ hold: 0, edges: 0 });
                return;
            }
            submitAction(ctl, act);
        }

        function safeCall(fn) {
            try { return fn(); } catch (e) {
                setError('bridge_error', '브리지 호출 실패: ' + (e && e.message ? e.message : e));
                return undefined;
            }
        }

        function onAdapterEvent(kind, stateName, reasonName) {
            if (stateName === 'manual') {
                disposePolicy();
                lastEpisode = null;
            }
            var info = reasonInfo(reasonName);
            // 호스트가 이미 자세한 메시지로 같은 코드를 기록했으면 일반 문구로 덮지 않는다.
            if (info.kind === 'error' && !(lastError && lastError.code === reasonName)) setError(reasonName, info.text);
            emit({ type: 'transition', kind: kind, state: stateName, reason: reasonName });
        }

        // ---------- 공개 API ----------
        var api = {
            schema: HOST_SCHEMA,
            ready: readyPromise,
            markReady: function () { readyResolve(api.state()); },

            // 실행기·진단용: 연결된 어댑터(브리지)를 그대로 돌려준다. 읽기(read/snapshot/state) 용도이며 소유권 전환은 이 API로 한다.
            getAdapter: function () { return adapter; },

            // 어댑터 연결. kind는 'real'(실제 브리지) 또는 'mock'(검증용). 이후 모든 결과에 kind가 표시된다.
            attach: function (a, kind) {
                var need = ['enable', 'resume', 'suspend', 'disable', 'state', 'onEvent', 'onFrame', 'setObserve'];
                for (var i = 0; i < need.length; i++) {
                    if (!a || typeof a[need[i]] !== 'function') {
                        throw new Error('어댑터에 ' + need[i] + '()가 없습니다.');
                    }
                }
                if (adapter) api.detach();
                adapter = a;
                adapterKind = kind === 'mock' ? 'mock' : 'real';
                lastError = null;
                adapter.onEvent(onAdapterEvent);
                adapter.onFrame(frameDriver);
                emit({ type: 'attach', adapter: adapterKind });
            },

            detach: function () {
                if (!adapter) return;
                safeCall(function () { adapter.disable('host_request'); });
                safeCall(function () { adapter.onFrame(null); });
                safeCall(function () { adapter.onEvent(null); });
                disposePolicy();
                adapter = null;
                adapterKind = null;
                emit({ type: 'detach' });
            },

            // 호스트 밖(셸)에서 난 오류를 상태에 남긴다. 예: 정책 번들을 불러오지 못함.
            reportError: function (code, message) {
                setError(code, message);
            },

            setUnavailable: function (why) {
                unavailableReason = why;
                emit({ type: 'unavailable', reason: why });
            },

            // 정책 객체를 그대로 쓴다(호스트는 reset만 부른다).
            setPolicy: function (obj, info) {
                disposePolicy();
                policy = null;
                policySource = obj ? { kind: 'object', obj: obj } : null;
                policyInfo = obj ? (info || (typeof obj.describe === 'function' ? obj.describe() : { id: 'custom' })) : null;
                if (obj) policy = obj;
                resetStats();
                emit({ type: 'policy', policy: policyInfo });
            },

            // 정책 번들 모듈(init(config, host) → policy)을 쓴다. enable마다 init하고 manual 전환 때 dispose한다.
            setPolicyModule: function (mod, config, info) {
                if (!mod || typeof mod.init !== 'function') throw new Error('정책 모듈에 init()이 없습니다.');
                disposePolicy();
                policy = null;
                policySource = { kind: 'module', mod: mod, config: config, url: info && info.url };
                var meta = mod.meta || {};
                policyInfo = { id: (info && info.id) || meta.id || 'unknown', version: meta.version || null, url: (info && info.url) || null };
                resetStats();
                emit({ type: 'policy', policy: policyInfo });
            },

            enable: function () {
                if (!adapter) return 'unavailable';
                if (!policySource) return 'no_policy';
                if (!ensurePolicyInstance()) return 'policy_error';
                resetPolicy('enable');
                lastEpisode = null;
                lastError = null;
                safeCall(function () { adapter.setObserve(true); });
                var res = safeCall(function () { return adapter.enable(); });
                return res === undefined ? 'bridge_error' : res;
            },

            resume: function () {
                if (!adapter) return 'unavailable';
                if (!policySource) return 'no_policy';
                if (!ensurePolicyInstance()) return 'policy_error';
                resetPolicy('resume');
                lastError = null;
                safeCall(function () { adapter.setObserve(true); });
                var res = safeCall(function () { return adapter.resume(); });
                return res === undefined ? 'bridge_error' : res;
            },

            suspend: function (reason) {
                if (!adapter) return 'unavailable';
                var r = reason || 'host_request';
                var res = safeCall(function () { adapter.suspend(r); return 'ok'; });
                return res === undefined ? 'bridge_error' : res;
            },

            disable: function (reason) {
                if (!adapter) return 'unavailable';
                var r = reason || 'host_request';
                var res = safeCall(function () { adapter.disable(r); return 'ok'; });
                return res === undefined ? 'bridge_error' : res;
            },

            // 창 포커스 상실·탭 숨김. ai_active일 때만 정지시키고, 돌아와도 자동 재개하지 않는다(CONTRACT 4절).
            notifyFocusLost: function () {
                if (!adapter) return 'unavailable';
                var s = safeCall(function () { return adapter.state(); });
                if (!s || s.owner !== 'ai_active') return 'noop';
                return api.suspend('focus_lost');
            },

            setBuildInfo: function (info) {
                build = {
                    flavor: info && info.flavor ? String(info.flavor) : 'unknown',
                    taiseiCommit: (info && info.taiseiCommit) || null,
                    source: (info && info.source) || null,
                };
                emit({ type: 'build', build: build });
            },

            onEvent: function (cb) {
                if (typeof cb !== 'function') throw new Error('onEvent에는 함수가 필요합니다.');
                listeners.push(cb);
                return function () {
                    var i = listeners.indexOf(cb);
                    if (i !== -1) listeners.splice(i, 1);
                };
            },

            decisionStats: decisionStats,
            reasonInfo: reasonInfo,

            state: function () {
                var s = adapter ? safeCall(function () { return adapter.state(); }) : null;
                s = s || {};
                var reasonName = s.owner_reason_name || 'none';
                var flavor = build.flavor;
                var warnings = [];
                if (flavor === 'developer') {
                    warnings.push({ code: 'developer_build', text: '개발자 빌드입니다. 원본 규칙 보존이 확정되지 않았습니다(검증 전). 이 결과를 원래 규칙의 클리어 증거로 쓰지 않습니다.' });
                } else if (flavor === 'unknown') {
                    warnings.push({ code: 'build_unknown', text: '빌드 종류를 확인하지 못했습니다(build-info.json 없음). 원본 규칙 보존을 확정할 수 없습니다.' });
                }
                if (adapterKind === 'mock') {
                    warnings.push({ code: 'mock_adapter', text: '검증용 mock 어댑터입니다. 실제 게임 입력이 아니며 결과는 클리어 증거가 아닙니다.' });
                }
                return {
                    schema: HOST_SCHEMA,
                    available: !!adapter,
                    adapter: adapterKind,
                    unavailableReason: adapter ? null : unavailableReason,
                    mode: adapter ? (s.owner || 'manual') : 'manual',
                    reason: reasonName,
                    reasonInfo: reasonInfo(reasonName),
                    ownerEvents: s.owner_events || 0,
                    inStage: !!s.in_stage,
                    paused: !!s.paused,
                    episodeId: s.episode_id === undefined ? null : s.episode_id,
                    lastFrame: s.last_frame === undefined ? null : s.last_frame,
                    gameover: s.gameover === undefined ? null : s.gameover,
                    buildFlavor: flavor,
                    taiseiCommit: build.taiseiCommit,
                    rulesPreserved: flavor === 'release' ? 'release_build' : 'unverified',
                    policy: policyInfo,
                    warnings: warnings,
                    lastError: lastError,
                    decision: decisionStats(),
                    // 수동 모드의 자동 발사(shot_inverted)는 물리 키에만 적용되고 AI의 hold.SHOT은 항상 "공격 중"이다(CONTRACT 6.1).
                    shotSemantics: { aiHoldShot: 'always_attacking', manualInversion: 'physical_key_only' },
                };
            },
        };

        return api;
    }

    return {
        HOST_SCHEMA: HOST_SCHEMA,
        REASON_INFO: REASON_INFO,
        HOST_REASONS: HOST_REASONS,
        createHost: createHost,
    };
});
