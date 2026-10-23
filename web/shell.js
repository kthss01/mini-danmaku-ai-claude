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
    };

    // 검증·디버깅용 공개 상태. 자동화 검증(mock/실제)에서 window.taiseiShell로 읽는다.
    var shell = {
        state: 'checking',
        config: cfg,
        gl: null,
        instance: null,
        hadFirstFrame: false,
        lastStatus: '',
        logLines: [],
        errors: [],
    };
    window.taiseiShell = shell;

    var LOG_LIMIT = 500;

    // ---------- 로그 ----------
    function log(text) {
        shell.logLines.push(text);
        if (shell.logLines.length > LOG_LIMIT) {
            shell.logLines.splice(0, shell.logLines.length - LOG_LIMIT);
        }
        if (!els.logPanel.hidden) {
            els.log.value += text + '\n';
            els.log.scrollTop = els.log.scrollHeight;
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
        els.errorMessage.textContent = message;
        els.errorDetail.textContent = text;
        if (shell.hadFirstFrame) {
            document.body.classList.add('had-first-frame');
        }
        setState('error');
    }

    function setExited(code) {
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

    // Emscripten/Taisei가 호출하는 Module.setStatus. 업스트림 셸과 같은 형식("텍스트 (현재/전체)")을 해석한다.
    var moduleSetStatus = (function () {
        var last = { time: 0, text: null };
        return function (text, force) {
            text = text == null ? '' : String(text);
            if (!text && !force) return;
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
            },
            print: function () {
                var text = joinArgs(arguments);
                console.log(text);
                log(text);
            },
            printErr: function () {
                var text = joinArgs(arguments);
                console.error(text);
                log('[ERR] ' + text);
                // 리소스 내려받기 실패는 게임이 계속 재시도하므로 화면에 알린다(원인 해결은 서버/산출물 쪽).
                if (/Failed to download/i.test(text)) {
                    els.hudStatus.textContent = '리소스 내려받기 실패(재시도 중) - 로그 확인';
                    els.loadWarning.textContent = '리소스 내려받기 실패(게임이 재시도합니다): ' + text;
                }
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
    });
    window.addEventListener('focus', function () {
        log('[SHELL] window focus');
        els.focusHint.hidden = true;
    });
    document.addEventListener('visibilitychange', function () {
        log('[SHELL] visibility: ' + document.visibilityState);
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
