/*
 * Taisei 웹 셸.
 * 역할: 환경 확인 → 시작 버튼 → 게임 로더/모듈 로딩 진행 표시 → 게임 화면 → 오류/종료 상태.
 * 게임 산출물과의 연결 지점은 shell-config.js(window.TAISEI_SHELL_CONFIG)에만 둔다.
 *
 * 게임 모듈(Emscripten preamble.js/postamble.js)이 셸에 기대하는 Module 필드:
 *   canvas, preinitializedWebGLContext, setStatus(text, force), onFirstFrame(), print(), printErr()
 * 셸이 게임 인스턴스에서 호출하는 메서드: initFilesystem(), callMain()
 */
(function () {
    'use strict';

    var RAW = window.TAISEI_SHELL_CONFIG || {};
    var cfg = {
        gameBase: typeof RAW.gameBase === 'string' ? RAW.gameBase : '',
        gameScript: RAW.gameScript || 'taisei.js',
        factoryName: RAW.factoryName || 'createTaisei',
        requiredInstanceMethods: RAW.requiredInstanceMethods || ['initFilesystem', 'callMain'],
        licenseFile: RAW.licenseFile || 'COPYING.txt',
        // AI 연결(이슈 #24). 파일 위치는 페이지 기준 상대 경로이며 패키징 규칙(세션 1)이 정하면 shell-config.js에서 바꾼다.
        aiBridgeUrl: RAW.aiBridgeUrl || 'ai/bridge/taisei-ai-bridge.mjs',
        aiPolicyBase: RAW.aiPolicyBase || 'ai/policies/',
        aiMockScript: RAW.aiMockScript || 'ai-mock-adapter.js',
        buildInfoUrl: RAW.buildInfoUrl || '../build-info.json',
    };

    function $(id) { return document.getElementById(id); }

    var els = {
        canvas: $('canvas'),
        focusHint: $('focus-hint'),
        start: $('start'),
        retry: $('retry'),
        restart: $('restart'),
        status: $('status'),
        statusDetail: $('status-detail'),
        loadWarning: $('load-warning'),
        progress: $('progress'),
        errorMessage: $('error-message'),
        errorDetail: $('error-detail'),
        exitMessage: $('exit-message'),
        unsupportedReasons: $('unsupported-reasons'),
        hud: $('hud'),
        hudStatus: $('hud-status'),
        hudWarning: $('hud-warning'),
        hudControls: $('hud-controls'),
        hudFullscreen: $('hud-fullscreen'),
        hudLog: $('hud-log'),
        controls: $('controls'),
        controlsPopover: $('controls-popover'),
        controlsPopoverContent: $('controls-popover-content'),
        controlsClose: $('controls-close'),
        logPanel: $('log-panel'),
        log: $('log'),
        licenseLink: $('license-link'),
        aiPanel: $('ai-panel'),
        aiBadge: $('ai-badge'),
        aiAdapter: $('ai-adapter'),
        aiStart: $('ai-start'),
        aiSuspend: $('ai-suspend'),
        aiResume: $('ai-resume'),
        aiManual: $('ai-manual'),
        aiDetailsToggle: $('ai-details-toggle'),
        aiMessage: $('ai-message'),
        aiWarnings: $('ai-warnings'),
        aiDetails: $('ai-details'),
        aiPolicy: $('ai-policy'),
        aiDecision: $('ai-decision'),
    };

    // 검증·디버깅용 공개 상태. 자동화 검증(mock/실제)에서 window.taiseiShell로 읽는다.
    var shell = {
        state: 'checking',
        config: cfg,
        gl: null,
        instance: null,
        hadFirstFrame: false,
        lastStatus: '',
        // 런타임이 포기한 리소스 내려받기 오류(fork PR #1 계약: setStatus("Error: Failed to download <url> (HTTP status N)")).
        // 치명적 abort가 뒤따르면 오류 상세에 함께 보여주고, 선택 리소스면 경고로만 남긴다.
        downloadErrors: [],
        logLines: [],
        errors: [],
    };
    window.taiseiShell = shell;

    var LOG_LIMIT = 500;
    shell.log = log; // 검증용: 로그 버퍼 동작을 밖에서 확인할 수 있게 노출

    // ---------- 로그 ----------
    function log(text) {
        shell.logLines.push(text);
        var trimmed = false;
        if (shell.logLines.length > LOG_LIMIT) {
            shell.logLines.splice(0, shell.logLines.length - LOG_LIMIT);
            trimmed = true;
        }
        if (!els.logPanel.hidden) {
            // 표시 버퍼도 LOG_LIMIT 줄로 유지한다. 잘려 나간 뒤에는 전체를 다시 그린다.
            if (trimmed) {
                renderLog();
            } else {
                els.log.value += text + '\n';
                els.log.scrollTop = els.log.scrollHeight;
            }
        }
    }

    function renderLog() {
        els.log.value = shell.logLines.join('\n') + '\n';
        els.log.scrollTop = els.log.scrollHeight;
    }

    function joinArgs(args) {
        return Array.prototype.slice.call(args).join(' ');
    }

    // ---------- 상태 전환 ----------
    function setState(name) {
        shell.state = name;
        document.body.setAttribute('data-state', name);
        var views = document.querySelectorAll('#panel [data-view]');
        for (var i = 0; i < views.length; i++) {
            var list = views[i].getAttribute('data-view').split(/\s+/);
            views[i].classList.toggle('visible', list.indexOf(name) !== -1);
        }
        els.hud.hidden = name !== 'playing';
        if (name !== 'playing') els.aiPanel.hidden = true;
        else if (aiState.panel) renderAI();
        if (name !== 'playing') {
            els.controlsPopover.hidden = true;
        }
        if (name !== 'playing' && name !== 'error') {
            els.focusHint.hidden = true;
        }
        log('[SHELL] state: ' + name);
    }

    function describeError(err) {
        if (!err) return '';
        if (err instanceof Error) {
            var first = err.stack ? String(err.stack).split('\n').slice(0, 3).join('\n') : '';
            return err.message + (first ? '\n' + first : '');
        }
        if (typeof err === 'object' && err.message) return String(err.message);
        return String(err);
    }

    // 첫 오류만 화면에 표시한다. 이후 오류는 로그에만 남긴다.
    function fail(message, detail) {
        var text = detail ? describeError(detail) : '';
        shell.errors.push({ message: message, detail: text });
        log('[SHELL] error: ' + message + (text ? ' :: ' + text : ''));
        if (shell.state === 'error') return;
        // 직전에 리소스 내려받기 실패가 있었다면 abort의 원인일 가능성이 높으므로 상세에 함께 보여준다.
        if (shell.downloadErrors.length) {
            var last = shell.downloadErrors[shell.downloadErrors.length - 1];
            message += ' 리소스 내려받기 실패가 원인일 수 있습니다.';
            text = '마지막 리소스 오류: ' + last + (shell.downloadErrors.length > 1 ? ' (총 ' + shell.downloadErrors.length + '건)' : '')
                + (text ? '\n' + text : '');
        }
        releaseAI('bridge_error'); // 게임 모듈이 멈추면 AI 입력을 쥐고 있지 않게 먼저 해제한다
        els.errorMessage.textContent = message;
        els.errorDetail.textContent = text;
        if (shell.hadFirstFrame) {
            document.body.classList.add('had-first-frame');
        }
        setState('error');
    }

    function setExited(code) {
        releaseAI('host_request');
        els.exitMessage.textContent = code === 0 || code === undefined
            ? '게임이 정상적으로 종료되었습니다.'
            : '게임이 종료 코드 ' + code + '로 끝났습니다.';
        setState('exited');
    }

    // ---------- 로딩 상태 표시 ----------
    function showStatus(text, current, total) {
        shell.lastStatus = text;
        if (shell.state === 'playing') {
            els.hudStatus.textContent = text ? (total ? text + ' (' + current + '/' + total + ')' : text) : '';
            return;
        }
        els.status.textContent = text || '';
        if (total) {
            els.progress.hidden = false;
            els.progress.max = total;
            els.progress.value = current;
            els.statusDetail.textContent = current + ' / ' + total;
        } else {
            els.progress.hidden = true;
            els.statusDetail.textContent = '';
        }
    }

    var STATUS_MAP = [
        [/^Preparing/i, '게임 모듈을 준비하는 중'],
        [/^All downloads complete/i, '내려받기 완료'],
        [/^Downloading/i, '게임 데이터를 내려받는 중'],
        [/^Prefetching resources/i, '리소스를 미리 내려받는 중'],
        [/^Running/i, '게임을 시작하는 중'],
    ];

    function translateStatus(text) {
        for (var i = 0; i < STATUS_MAP.length; i++) {
            if (STATUS_MAP[i][0].test(text)) return STATUS_MAP[i][1];
        }
        return text;
    }

    // 런타임이 포기한 리소스 내려받기 오류를 보존하고 경고로 표시한다. 치명 여부는 런타임이 정한다
    // (필수 리소스면 abort가 뒤따르고, 선택 리소스면 게임이 계속된다).
    function noteDownloadError(text) {
        // 같은 리소스에 대한 로그 문구와 setStatus 문구가 연달아 오면 한 건으로 합친다(최신 문구 유지).
        var id = (text.match(/data\/[0-9a-f]{8,}/i) || [null])[0];
        var n0 = shell.downloadErrors.length;
        if (id && n0 && shell.downloadErrors[n0 - 1].indexOf(id) !== -1) {
            shell.downloadErrors[n0 - 1] = text;
        } else {
            shell.downloadErrors.push(text);
        }
        var n = shell.downloadErrors.length;
        var label = '리소스 내려받기 실패' + (n > 1 ? '(' + n + '건)' : '') + ': ' + text;
        els.loadWarning.textContent = label;
        els.hudWarning.textContent = label;
        els.hudWarning.hidden = false;
        log('[SHELL] download error: ' + text);
    }

    // Taisei 로그(print/printErr)에서 내려받기 실패를 찾아둔다. 수정 전 빌드(무한 재시도)는 setStatus를 보내지 않고
    // log_error만 남기므로 첫 실패 문구를 잡아 경고로 보여준다. 이미 기록된 뒤에는 반복 문구를 무시한다.
    function inspectGameLog(text) {
        var m = text.match(/(Failed to download .*|Giving up on .*)$/i);
        if (!m) return;
        // 수정 전 빌드는 같은 문구를 무한히 반복하므로 첫 실패만 기록한다. 다른 리소스의 실패는 새로 기록한다.
        var id = (m[1].match(/data\/[0-9a-f]{8,}/i) || [null])[0];
        var dup = shell.downloadErrors.some(function (e) { return id && e.indexOf(id) !== -1; });
        if (!dup) noteDownloadError(m[1]);
    }

    // Emscripten/Taisei가 호출하는 Module.setStatus. 업스트림 셸과 같은 형식("텍스트 (현재/전체)")을 해석한다.
    var moduleSetStatus = (function () {
        var last = { time: 0, text: null };
        return function (text, force) {
            text = text == null ? '' : String(text);
            if (!text && !force) return;
            // fork PR #1 계약: 내려받기를 포기하면 "Error: Failed to download <url> (HTTP status N)"을 force로 보낸다.
            if (/^Error:/i.test(text)) {
                noteDownloadError(text.replace(/^Error:\s*/i, ''));
                return;
            }
            if (text === last.text) return;
            var m = text.match(/([^(]+)\((\d+(\.\d+)?)\/(\d+)\)/);
            var now = Date.now();
            if (m && now - last.time < 30) return; // 진행률 갱신은 30ms 간격으로 제한
            last.time = now;
            last.text = text;
            if (m) {
                showStatus(translateStatus(m[1].trim()), parseInt(m[2], 10), parseInt(m[4], 10));
            } else {
                showStatus(text ? translateStatus(text.replace(/\.\.\.$/, '').trim()) : '');
            }
            if (text) log('[STATUS] ' + text);
        };
    })();

    // ---------- 환경 확인 ----------
    var GL_ATTRIBUTES = {
        alpha: false,
        antialias: false,
        depth: false,
        powerPreference: 'high-performance',
        premultipliedAlpha: true,
        preserveDrawingBuffer: false,
        stencil: false,
    };

    function checkSupport() {
        var reasons = [];
        if (typeof WebAssembly !== 'object' || typeof WebAssembly.instantiate !== 'function') {
            reasons.push('WebAssembly를 지원하지 않습니다.');
        }
        if (typeof BigInt === 'undefined') {
            reasons.push('BigInt를 지원하지 않습니다(게임 모듈이 WASM BigInt 연동을 요구합니다).');
        }
        if (!window.indexedDB) {
            reasons.push('IndexedDB를 사용할 수 없습니다. 설정·리플레이·리소스 캐시를 저장할 수 없어 실행할 수 없습니다(사생활 보호 모드 또는 사이트 데이터 차단 확인).');
        }
        var gl = null;
        try {
            gl = els.canvas.getContext('webgl2', GL_ATTRIBUTES);
        } catch (e) {
            gl = null;
        }
        if (!gl) {
            reasons.push('WebGL 2 컨텍스트를 만들 수 없습니다. 하드웨어 가속이 꺼져 있거나 GPU/드라이버가 지원하지 않을 수 있습니다.');
        }
        return { reasons: reasons, gl: gl };
    }

    // ---------- AI 모드 (이슈 #24) ----------
    // 소유권의 진실은 브리지(ai/bridge, 세션 2)다. 셸은 window.taiseiAI(ai-host.js)를 통해 보여주고 전환만 요청한다.
    // 브리지가 없는 빌드(현재 공개 사이트)에서는 ?ai= 로 요청하지 않는 한 패널이 나타나지 않으므로 수동 플레이는 달라지지 않는다.
    //   ?ai=0|off       AI 연결을 시도하지 않는다
    //   ?ai=1           브리지가 없어도 패널을 보여주고 사용 불가 사유를 알린다
    //   ?ai=mock        검증용 mock 어댑터(실제 게임 입력이 아님, 패널에 표시)
    //   ?policy=<id>    ai/policies/<id>/index.js 정책 번들을 불러온다
    var aiHost = window.taiseiAI;
    var aiState = { requested: null, panel: false, pollTimer: null, resultMessage: '', detailsOpen: false };
    shell.ai = aiState;

    function aiQuery(name) {
        try { return new URLSearchParams(window.location.search).get(name); } catch (e) { return null; }
    }

    function releaseAI(reason) {
        if (!aiHost || !aiHost.state().available) return;
        try { aiHost.disable(reason); } catch (e) { log('[SHELL] AI release failed: ' + describeError(e)); }
    }

    // 창 포커스 상실·탭 숨김: ai_active만 정지시키고 돌아와도 자동 재개하지 않는다(CONTRACT 4절).
    function suspendAIOnFocusLoss(why) {
        if (!aiHost || shell.state !== 'playing') return;
        var r = aiHost.notifyFocusLost();
        if (r === 'ok') log('[SHELL] AI suspended (focus_lost, ' + why + ')');
    }

    function aiShowPanel(show) {
        aiState.panel = show;
        els.aiPanel.hidden = !show || shell.state !== 'playing';
        if (show && !aiState.pollTimer) {
            // 일시정지·메뉴 중에는 이벤트가 없으므로 상태 블록을 주기적으로 읽는다(작은 상태 블록이라 비용이 거의 없다).
            aiState.pollTimer = setInterval(renderAI, 250);
        }
        renderAI();
    }

    var MODE_LABEL = { manual: '수동', ai_active: 'AI 동작 중', ai_suspended: 'AI 정지' };

    function renderAI() {
        if (!aiState.panel) return;
        els.aiPanel.hidden = shell.state !== 'playing';
        var s = aiHost.state();
        var mode = s.available ? s.mode : 'unavailable';
        els.aiBadge.dataset.mode = mode;
        els.aiBadge.textContent = s.available ? MODE_LABEL[s.mode] || s.mode : 'AI 사용 불가';
        els.aiAdapter.textContent = s.adapter === 'mock' ? 'mock 어댑터' : '';

        var hasPolicy = !!s.policy;
        els.aiStart.hidden = !(s.available && s.mode === 'manual');
        els.aiStart.disabled = !hasPolicy;
        els.aiStart.title = hasPolicy ? '' : '정책이 없습니다. ?policy=<id> 로 정책 번들을 지정하세요.';
        els.aiSuspend.hidden = !(s.available && s.mode === 'ai_active');
        els.aiResume.hidden = !(s.available && s.mode === 'ai_suspended');
        els.aiManual.hidden = !(s.available && s.mode !== 'manual');

        // 메시지 우선순위: 사용 불가 → 방금 한 요청의 결과 → 오류 → 전환 사유 → 정책 없음
        var msg = '', kind = 'info';
        if (!s.available) {
            msg = s.unavailableReason || ''; kind = 'warn';
        } else if (aiState.resultMessage) {
            msg = aiState.resultMessage; kind = 'warn';
        } else if (s.lastError && s.mode === 'manual') {
            msg = s.lastError.message || s.reasonInfo.text; kind = 'error';
        } else if (s.reason !== 'none') {
            msg = s.reasonInfo.text; kind = s.reasonInfo.kind;
        } else if (!hasPolicy) {
            msg = '정책이 없습니다. ?policy=<id> 로 정책 번들을 지정하세요.'; kind = 'warn';
        }
        els.aiMessage.textContent = msg;
        els.aiMessage.dataset.kind = kind;
        els.aiPanel.dataset.attention = (kind === 'warn' || kind === 'error') && !!msg ? 'true' : 'false';

        els.aiWarnings.innerHTML = '';
        s.warnings.forEach(function (w) {
            var li = document.createElement('li');
            li.textContent = w.text;
            els.aiWarnings.appendChild(li);
        });

        els.aiDetails.hidden = !aiState.detailsOpen;
        if (aiState.detailsOpen) {
            els.aiPolicy.textContent = '정책: ' + (s.policy ? s.policy.id + (s.policy.version ? ' ' + s.policy.version : '') : '없음')
                + ' · 빌드: ' + s.buildFlavor + (s.taiseiCommit ? ' (Taisei ' + String(s.taiseiCommit).slice(0, 8) + ')' : '')
                + ' · 규칙 보존: ' + s.rulesPreserved;
            var d = s.decision;
            els.aiDecision.textContent = '에피소드 ' + (s.episodeId === null ? '-' : s.episodeId) + ' · 프레임 ' + (s.lastFrame === null ? '-' : s.lastFrame)
                + ' · 판단 ' + d.count + '회' + (d.count ? ' p50 ' + d.p50_ms.toFixed(2) + ' ms / p95 ' + d.p95_ms.toFixed(2) + ' ms / 최대 ' + d.max_ms.toFixed(2) + ' ms' : '');
        }
    }

    var RESULT_TEXT = {
        unavailable: 'AI 브리지가 연결되지 않았습니다.',
        no_policy: '정책이 없습니다. ?policy=<id> 로 정책 번들을 지정하세요.',
        policy_error: '정책을 시작하지 못했습니다.',
        bridge_error: '브리지 호출이 실패했습니다.',
        noop: '이미 그 상태입니다.',
    };

    function aiRequest(fn) {
        var result = fn();
        // not_playing은 상태 사유(not_playing)가 이미 메시지로 나오므로 별도 결과 문구를 쓰지 않는다.
        aiState.resultMessage = result === 'ok' || result === 'not_playing' ? '' : (RESULT_TEXT[result] || String(result));
        if (result === 'not_playing') aiState.resultMessage = aiHost.reasonInfo('not_playing').text;
        renderAI();
        focusCanvas();
    }

    els.aiStart.addEventListener('click', function () { aiRequest(function () { return aiHost.enable(); }); });
    els.aiResume.addEventListener('click', function () { aiRequest(function () { return aiHost.resume(); }); });
    els.aiSuspend.addEventListener('click', function () { aiRequest(function () { return aiHost.suspend('host_request'); }); });
    els.aiManual.addEventListener('click', function () { aiRequest(function () { return aiHost.disable('host_request'); }); });
    els.aiDetailsToggle.addEventListener('click', function () {
        aiState.detailsOpen = !aiState.detailsOpen;
        els.aiDetailsToggle.textContent = aiState.detailsOpen ? '▴' : '▾';
        renderAI();
        focusCanvas();
    });
    aiHost.onEvent(function (event) {
        if (event.type === 'transition' || event.type === 'error') aiState.resultMessage = '';
        if (event.type === 'transition') log('[AI] ' + event.state + ' (' + event.reason + ')');
        if (event.type === 'error') log('[AI] error ' + event.code + ': ' + event.message);
        renderAI();
    });

    // 정책 번들 불러오기. id(ai/policies/<id>/index.js) 또는 URL을 받는다. 실행기도 이 함수를 쓴다.
    aiHost.loadPolicy = function (idOrUrl, config) {
        var url = /[\/.]/.test(idOrUrl) ? idOrUrl : cfg.aiPolicyBase + idOrUrl + '/index.js';
        var abs = new URL(url, document.baseURI).href;
        return import(abs).then(function (mod) {
            var base = (mod.meta && mod.meta.default_config) || {};
            var merged = Object.assign({}, base, config || {});
            aiHost.setPolicyModule(mod, merged, { id: (mod.meta && mod.meta.id) || idOrUrl, url: abs });
            log('[AI] policy loaded: ' + abs);
            return aiHost.state().policy;
        });
    };

    function loadBuildInfo() {
        return fetch(cfg.buildInfoUrl, { cache: 'no-store' }).then(function (res) {
            if (!res.ok) throw new Error('HTTP ' + res.status);
            return res.json();
        }).then(function (info) {
            var b = info && info.build ? info.build : {};
            // 릴리스 산출물은 flavor를 기록하지 않는다(#20 v0.1 B). 개발자 빌드만 flavor: "developer"를 남긴다.
            aiHost.setBuildInfo({
                flavor: b.flavor || 'release',
                taiseiCommit: b.taiseiCommit || null,
                source: cfg.buildInfoUrl,
            });
        }).catch(function (e) {
            aiHost.setBuildInfo({ flavor: 'unknown', source: null });
            log('[AI] build-info.json을 읽지 못했습니다: ' + describeError(e));
        });
    }

    function attachMock() {
        return loadScript(cfg.aiMockScript).then(function () {
            var mock = window.taiseiAIMock;
            if (!mock) throw new Error('mock 어댑터가 전역 taiseiAIMock을 정의하지 않습니다.');
            var adapter = mock.createMockAdapter();
            adapter.sim.start();
            aiHost.attach(adapter, 'mock');
            aiHost.setPolicy(mock.createSweepPolicy());
            window.taiseiAIMockAdapter = adapter; // 검증용: adapter.sim으로 일시정지·사용자 키 등을 재현한다
            // mock에서는 실제 키보드로 사용자 키 전환(CONTRACT 4.3)과 일시정지(Esc)를 흉내 낸다. 실제 브리지는 C에서 처리한다.
            var MOCK_GAME_KEYS = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'z', 'Z', 'x', 'X', 'c', 'C', 'Shift', 'Control'];
            window.addEventListener('keydown', function (event) {
                if (event.repeat) return;
                if (event.key === 'Escape') adapter.sim.setPaused(!adapter.state().paused);
                else if (MOCK_GAME_KEYS.indexOf(event.key) !== -1) adapter.sim.userKey();
            }, true);
            log('[AI] mock 어댑터 연결(실제 게임 입력이 아님)');
        });
    }

    function attachRealBridge() {
        var inst = shell.instance;
        if (!inst || typeof inst._taisei_ai_abi_version !== 'function') {
            aiHost.setUnavailable('이 게임 빌드에는 AI 브리지가 없습니다(taisei_ai_* 내보내기 없음).');
            return Promise.resolve(false);
        }
        var url = new URL(cfg.aiBridgeUrl, document.baseURI).href;
        return import(url).then(function (mod) {
            aiHost.attach(mod.createBridge(inst), 'real');
            log('[AI] 브리지 연결: ' + url);
            return true;
        }).catch(function (e) {
            aiHost.setUnavailable('AI 브리지를 불러오지 못했습니다: ' + (e && e.message ? e.message : e));
            aiState.showUnavailable = true; // 브리지가 있는데 불러오지 못한 것은 사용자가 알아야 하는 결함이다
            log('[AI] 브리지 연결 실패: ' + describeError(e));
            return false;
        });
    }

    function initAI() {
        var req = aiQuery('ai');
        aiState.requested = req;
        if (req === '0' || req === 'off') { aiHost.markReady(); return; }
        var forced = req !== null; // ?ai= 가 있으면 브리지가 없어도 패널로 사유를 알린다
        var attach = req === 'mock' ? attachMock() : attachRealBridge();
        Promise.all([loadBuildInfo(), attach]).then(function () {
            var policyId = aiQuery('policy');
            if (aiHost.state().available && policyId && req !== 'mock') {
                return aiHost.loadPolicy(policyId).catch(function (e) {
                    aiHost.reportError('policy_error', '정책을 불러오지 못했습니다: ' + (e && e.message ? e.message : e));
                    log('[AI] policy load failed: ' + describeError(e));
                });
            }
        }).catch(function (e) {
            aiHost.setUnavailable('AI 연결 중 오류: ' + (e && e.message ? e.message : e));
            log('[AI] init failed: ' + describeError(e));
        }).then(function () {
            aiShowPanel(forced || aiState.showUnavailable || aiHost.state().available);
            aiHost.markReady();
        });
    }

    // ---------- 게임 로딩 ----------
    function loadScript(url) {
        return new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = url;
            s.async = true;
            s.onload = function () { resolve(s); };
            s.onerror = function () { reject(new Error('스크립트 요청 실패: ' + url)); };
            document.head.appendChild(s);
        });
    }

    function buildModuleArg() {
        return {
            canvas: els.canvas,
            preinitializedWebGLContext: shell.gl,
            setStatus: moduleSetStatus,
            onFirstFrame: function () {
                shell.hadFirstFrame = true;
                setState('playing');
                showStatus('');
                focusCanvas();
                initAI();
            },
            print: function () {
                var text = joinArgs(arguments);
                console.log(text);
                log(text);
                inspectGameLog(text);
            },
            printErr: function () {
                var text = joinArgs(arguments);
                console.error(text);
                log('[ERR] ' + text);
                inspectGameLog(text);
            },
            onAbort: function (what) {
                fail('게임 모듈이 비정상 종료되었습니다(abort).', what);
            },
            onExit: function (code) {
                if (shell.state !== 'error') setExited(code);
            },
        };
    }

    function start() {
        if (shell.state !== 'ready') return;
        els.start.disabled = true;
        setState('loading');
        syncCanvasSize(); // 게임 화면이 보이기 시작하므로 드로잉 버퍼를 현재 뷰포트에 맞춘다.
        var scriptUrl = cfg.gameBase + cfg.gameScript;
        showStatus('게임 로더를 내려받는 중…');
        log('[SHELL] loading ' + scriptUrl);

        loadScript(scriptUrl).then(function () {
            var factory = window[cfg.factoryName];
            if (typeof factory !== 'function') {
                throw { contract: true, message: '게임 로더가 전역 함수 ' + cfg.factoryName + '를 정의하지 않습니다(산출물 계약 불일치: EXPORT_NAME 확인).' };
            }
            showStatus('게임 모듈(WebAssembly)을 내려받아 준비하는 중…');
            return factory(buildModuleArg());
        }, function (err) {
            throw { loader: true, message: '게임 로더(' + scriptUrl + ')를 불러오지 못했습니다. 빌드 산출물이 이 페이지와 같은 위치에 있는지, 서버가 해당 파일을 제공하는지 확인해주세요.', cause: err };
        }).then(function (instance) {
            for (var i = 0; i < cfg.requiredInstanceMethods.length; i++) {
                var name = cfg.requiredInstanceMethods[i];
                if (!instance || typeof instance[name] !== 'function') {
                    throw { contract: true, message: '게임 인스턴스에 ' + name + '() 가 없습니다(산출물 계약 불일치: preamble.js 확인).' };
                }
            }
            shell.instance = instance;
            showStatus('저장소를 준비하고 게임을 시작하는 중…');
            instance.initFilesystem();
            instance.callMain();
            // 이후 진행은 setStatus/onFirstFrame/onAbort/onExit 콜백이 이끈다.
        }).catch(function (err) {
            if (shell.state === 'error') return;
            if (err && (err.loader || err.contract)) {
                fail(err.message, err.cause);
            } else {
                fail('게임 모듈을 초기화하거나 시작하지 못했습니다.', err);
            }
        });
    }

    // ---------- 입력·포커스 정책 ----------
    // 페이지 스크롤이나 포커스 이동을 일으키는 키. 게임 중에는 브라우저 기본 동작을 막는다.
    var SCROLL_KEYS = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' ', 'PageUp', 'PageDown', 'Home', 'End', 'Tab'];

    function isTextTarget(target) {
        if (!target || !target.tagName) return false;
        var tag = target.tagName.toLowerCase();
        return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable;
    }

    function focusCanvas() {
        try { els.canvas.focus({ preventScroll: true }); } catch (e) { /* 무시 */ }
    }

    window.addEventListener('keydown', function (event) {
        // 브라우저 전체 화면(F11)과 개발자 도구(F12)는 게임에 전달하지 않고 브라우저가 처리하게 둔다(업스트림 셸과 동일).
        if (event.key === 'F11' || event.key === 'F12') {
            event.stopImmediatePropagation();
            return;
        }
        if (!els.controlsPopover.hidden && event.key === 'Escape') {
            els.controlsPopover.hidden = true;
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }
        if (shell.state !== 'playing' || isTextTarget(event.target)) return;
        if (SCROLL_KEYS.indexOf(event.key) !== -1) {
            event.preventDefault();
        }
    }, true);

    els.canvas.addEventListener('contextmenu', function (event) { event.preventDefault(); });
    els.canvas.addEventListener('mousedown', function () { focusCanvas(); });

    // 창 포커스를 잃으면 안내를 띄운다. 눌린 키 해제는 SDL(런타임, 세션 2)이 FOCUS_LOST로 처리한다.
    window.addEventListener('blur', function () {
        log('[SHELL] window blur');
        if (shell.state === 'playing') els.focusHint.hidden = false;
        suspendAIOnFocusLoss('blur');
    });
    window.addEventListener('focus', function () {
        log('[SHELL] window focus');
        els.focusHint.hidden = true;
    });
    document.addEventListener('visibilitychange', function () {
        log('[SHELL] visibility: ' + document.visibilityState);
        if (document.visibilityState === 'hidden') suspendAIOnFocusLoss('hidden');
    });

    // 업스트림 셸과 같은 방식으로 canvas 픽셀 크기를 CSS 크기에 맞춘다.
    function syncCanvasSize() {
        if (shell.state !== 'playing' && shell.state !== 'loading') return;
        var w = els.canvas.offsetWidth, h = els.canvas.offsetHeight;
        if (w > 0 && h > 0 && (els.canvas.width !== w || els.canvas.height !== h)) {
            els.canvas.width = w;
            els.canvas.height = h;
        }
    }
    window.addEventListener('resize', syncCanvasSize);

    // ---------- 전역 오류 ----------
    window.addEventListener('error', function (event) {
        if (shell.state !== 'loading' && shell.state !== 'playing') return;
        fail(shell.hadFirstFrame ? '게임 실행 중 오류가 발생했습니다.' : '게임을 불러오는 중 오류가 발생했습니다.',
            event.error || event.message);
    });
    window.addEventListener('unhandledrejection', function (event) {
        if (shell.state !== 'loading' && shell.state !== 'playing') return;
        fail(shell.hadFirstFrame ? '게임 실행 중 오류가 발생했습니다.' : '게임을 불러오는 중 오류가 발생했습니다.',
            event.reason);
    });

    // ---------- HUD ----------
    els.hudControls.addEventListener('click', function () {
        els.controlsPopoverContent.innerHTML = els.controls.innerHTML;
        els.controlsPopover.hidden = false;
    });
    els.controlsClose.addEventListener('click', function () {
        els.controlsPopover.hidden = true;
        focusCanvas();
    });
    els.controlsPopover.addEventListener('click', function (event) {
        if (event.target === els.controlsPopover) {
            els.controlsPopover.hidden = true;
            focusCanvas();
        }
    });
    els.hudFullscreen.addEventListener('click', function () {
        var root = document.documentElement;
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else if (root.requestFullscreen) {
            root.requestFullscreen().catch(function (e) { log('[SHELL] fullscreen failed: ' + describeError(e)); });
        }
        focusCanvas();
    });
    document.addEventListener('fullscreenchange', function () {
        log('[SHELL] fullscreen: ' + !!document.fullscreenElement);
        syncCanvasSize();
    });
    els.hudLog.addEventListener('click', function () {
        els.logPanel.hidden = !els.logPanel.hidden;
        if (!els.logPanel.hidden) renderLog();
        focusCanvas();
    });

    // ---------- 버튼 ----------
    els.start.addEventListener('click', start);
    els.retry.addEventListener('click', function () { window.location.reload(); });
    els.restart.addEventListener('click', function () { window.location.reload(); });
    els.licenseLink.href = cfg.licenseFile;

    // ---------- 시작 ----------
    var support = checkSupport();
    if (support.reasons.length) {
        els.unsupportedReasons.innerHTML = '';
        support.reasons.forEach(function (reason) {
            var li = document.createElement('li');
            li.textContent = reason;
            els.unsupportedReasons.appendChild(li);
        });
        setState('unsupported');
    } else {
        shell.gl = support.gl;
        setState('ready');
    }
})();
