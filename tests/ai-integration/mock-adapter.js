/*
 * AI 호스트(web/game/ai-host.js) 검증용 mock 브리지 어댑터.
 * 실제 게임이 아니다. docs/ai/CONTRACT.md(v1) 4~6절의 소유권 전이·제출 상태 코드·입력 해제 보장을 흉내 내서
 * 셸의 모드 전환 UI와 호스트 로직을 검증한다. 여기서 성공한 것은 "mock 성공"이며 실제 게임 성공이 아니다.
 *
 * 인터페이스는 ai/bridge/taisei-ai-bridge.mjs(세션 2)의 TaiseiAIBridge와 같은 이름·반환 형식을 쓴다:
 *   enable() resume() → 'ok' | 'not_playing' | 'noop'
 *   suspend(reason) disable(reason)
 *   state()  → status 블록 + owner / owner_reason_name
 *   onEvent(cb(kind, stateName, reasonName)) onFrame(cb(obs, ctl)) setObserve(on)
 *   ctl.submit({hold, edges}) → 'accepted' | 'stale' | 'dup' | 'wrong_episode' | 'not_active' | 'future' | 'no_stage'
 *
 * 검증용 제어: adapter.sim.* (일시정지, 사용자 키, 게임 오버, 스테이지 종료, 재시작, 브리지 오류, 프레임 진행).
 * 브라우저에서는 window.taiseiAIMock 으로 노출되고, ?ai=mock 일 때 셸이 이 파일을 불러 쓴다.
 */
(function (root, factory) {
    'use strict';
    var api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    } else {
        root.taiseiAIMock = api;
    }
})(typeof window !== 'undefined' ? window : this, function () {
    'use strict';

    var HOLD = { UP: 1, DOWN: 2, LEFT: 4, RIGHT: 8, FOCUS: 16, SHOT: 32, SKIP: 64 };
    var OWNER = ['manual', 'ai_active', 'ai_suspended'];

    function createMockAdapter(options) {
        options = options || {};
        var owner = 0;
        var reason = 'none';
        var events = 0;
        var inStage = options.inStage !== false;
        var paused = false;
        var episodeId = 1;
        var frame = 0;
        var gameover = 0;
        var observe = false;
        var slot = null;             // {target, hold, edges}
        var physicalHold = 0;        // 물리 키 입력(수동). mock에서는 sim.setPhysicalHold로 지정
        var appliedHold = 0;         // 마지막으로 게임에 적용된 hold
        var frameCb = null;
        var eventCb = null;
        var timer = null;

        var counters = { applied: 0, missing: 0, stale: 0, dup: 0, rejected: 0 };
        var appliedLog = [];         // {frame, source:'ai'|'physical', hold, edges}
        var errors = [];

        function setOwner(next, why) {
            owner = next;
            reason = why;
            events++;
            if (next !== 1) slot = null; // ai_active를 벗어나면 대기 슬롯·엣지를 즉시 버린다(CONTRACT 6.2)
            if (typeof eventCb === 'function') {
                try { eventCb(0, OWNER[next], why); } catch (e) { errors.push(e); }
            }
        }

        function canPlay() {
            return inStage && !paused && gameover === 0;
        }

        function makeObs() {
            return {
                meta: {
                    schema: 'taisei.ai.obs/1', frame: frame, episode_id: episodeId, gameover: gameover,
                    paused: paused ? 1 : 0, owner_state: owner, owner: OWNER[owner], owner_reason_name: reason,
                    overflow: 0, cheat_flags: 0,
                },
                player: { x: 240, y: 480, lives: 2, bombs: 3, phase_name: 'normal' },
                bullets: { n: 0 },
                lasers: { n: 0 },
                laser_segs: { n: 0 },
                enemies: { n: 0 },
                boss: { present: 0 },
            };
        }

        var adapter = {
            kind: 'mock',

            setObserve: function (on) { observe = !!on; },

            enable: function () {
                if (owner !== 0) return 'noop';
                if (!canPlay()) { setOwner(2, 'not_playing'); return 'not_playing'; }
                setOwner(1, 'none');
                return 'ok';
            },

            resume: function () {
                if (owner !== 2) return 'noop';
                if (!canPlay()) return 'not_playing';
                setOwner(1, 'none');
                return 'ok';
            },

            suspend: function (why) {
                if (owner === 0) return;            // manual에서는 무시
                if (owner === 2) return;            // 이미 정지면 첫 사유 유지
                setOwner(2, why || 'host_request');
            },

            disable: function (why) {
                slot = null;
                if (owner === 0) return;            // 이미 manual이면 전환 없음(사유·카운터 유지)
                setOwner(0, why || 'host_request');
            },

            state: function () {
                return {
                    in_stage: inStage ? 1 : 0, paused: paused ? 1 : 0, episode_id: episodeId, last_frame: frame,
                    owner_state: owner, owner_reason: reason, owner_events: events, replay_mode: 0, gameover: gameover,
                    observe: observe ? 1 : 0, owner: OWNER[owner], owner_reason_name: reason,
                };
            },

            onEvent: function (cb) { eventCb = cb; },
            onFrame: function (cb) { frameCb = cb; },
            takeErrors: function () { var e = errors; errors = []; return e; },
        };

        function submit(ep, target, hold, edges) {
            if (!inStage) return 'no_stage';
            if (owner !== 1) { counters.rejected++; return 'not_active'; }
            if (ep !== episodeId) { counters.rejected++; return 'wrong_episode'; }
            if (target < frame + 1) { counters.stale++; return 'stale'; }
            if (target > frame + 1) { counters.rejected++; return 'future'; }
            if (slot && slot.target === target) { counters.dup++; return 'dup'; }
            slot = { target: target, hold: hold | 0, edges: edges | 0 };
            return 'accepted';
        }

        // 논리 프레임 1틱: 입력 적용(process_input) → 프레임 증가 → 관측 캡처 → 동기 콜백.
        function tick() {
            if (!canPlay()) return;
            var next = frame + 1;
            if (owner === 1) {
                if (slot && slot.target === next) {
                    appliedHold = slot.hold; counters.applied++;
                    appliedLog.push({ frame: next, source: 'ai', hold: slot.hold, edges: slot.edges });
                    slot = null;
                } else {
                    counters.missing++;
                    appliedLog.push({ frame: next, source: 'ai', hold: appliedHold, edges: 0, missing: true });
                }
            } else {
                appliedHold = physicalHold;
                appliedLog.push({ frame: next, source: 'physical', hold: physicalHold, edges: 0 });
            }
            frame = next;
            if (appliedLog.length > 2000) appliedLog.splice(0, appliedLog.length - 2000);
            if ((observe || owner !== 0) && typeof frameCb === 'function') {
                var ctl = {
                    frame: frame, episode_id: episodeId,
                    submit: function (a) {
                        a = a || {};
                        return submit(episodeId, frame + 1, a.hold | 0, a.edges | 0);
                    },
                };
                try { frameCb(makeObs(), ctl); } catch (e) { errors.push(e); adapter.disable('policy_error'); }
            }
        }

        adapter.sim = {
            HOLD: HOLD,
            tick: function (n) { for (var i = 0; i < (n || 1); i++) tick(); },
            start: function (ms) {
                if (timer) return;
                timer = setInterval(tick, ms || 1000 / 60);
            },
            stop: function () { if (timer) { clearInterval(timer); timer = null; } },
            counters: function () { return JSON.parse(JSON.stringify(counters)); },
            appliedLog: function () { return appliedLog.slice(); },
            appliedHold: function () { return appliedHold; },
            hasPendingSlot: function () { return !!slot; },
            setPhysicalHold: function (bits) { physicalHold = bits | 0; },
            setPaused: function (on) {
                paused = !!on;
                if (paused && owner === 1) setOwner(2, 'pause');
            },
            userKey: function () {
                // 사용자 게임 키(TE_GAME_KEY_DOWN): ai_active 중이면 즉시 manual, 이벤트는 버림(CONTRACT 4.3)
                if (owner === 1) setOwner(0, 'user_input');
            },
            gameOver: function () {
                gameover = 2;
                if (owner === 1) setOwner(2, 'game_over');
                paused = true;
            },
            stageEnd: function () {
                gameover = 1;
                inStage = false;
                if (owner === 1) setOwner(2, 'stage_end');
            },
            restart: function () {
                if (owner === 1) setOwner(2, 'restart');
                episodeId++; frame = 0; gameover = 0; paused = false; inStage = true; slot = null; appliedHold = 0;
            },
            newEpisodeWhileActive: function () {
                // 새 에피소드 진입 시 아직 ai_active이면 restart 사유로 정지(CONTRACT 4.1)
                if (owner === 1) setOwner(2, 'restart');
                episodeId++; frame = 0; slot = null; appliedHold = 0;
            },
            bumpEpisodeKeepActive: function () {
                // 방어 경로 검증용: 계약상 새 에피소드는 ai_suspended(restart)이지만, ai_active인 채 episode_id만 바뀐 관측을 흉내 낸다
                episodeId++; frame = 0; slot = null; appliedHold = 0;
            },
            bridgeError: function () {
                if (owner !== 0) setOwner(0, 'bridge_error');
            },
            leaveStage: function () {
                inStage = false;
                if (owner === 1) setOwner(2, 'stage_end');
            },
            enterStage: function () { inStage = true; paused = false; gameover = 0; },
        };

        return adapter;
    }

    // 셸 데모(?ai=mock)용 정책: 좌우로 천천히 움직이며 계속 공격한다. 실제 정책(세션 3)이 아니다.
    function createSweepPolicy() {
        var n = 0;
        return {
            decide: function () {
                n++;
                var dir = Math.floor(n / 90) % 2 === 0 ? HOLD.LEFT : HOLD.RIGHT;
                return { hold: dir | HOLD.SHOT, edges: 0, request: null };
            },
            reset: function () { n = 0; },
            describe: function () { return { id: 'mock-sweep', version: '0.0.0-mock' }; },
        };
    }

    return { createMockAdapter: createMockAdapter, createSweepPolicy: createSweepPolicy, HOLD: HOLD };
});
