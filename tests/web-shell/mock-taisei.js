/*
 * 웹 셸(web/) 검증용 가짜 게임 로더.
 * 실제 taisei.js(Emscripten MODULARIZE, EXPORT_NAME=createTaisei)와 같은 계약으로 전역 createTaisei를 정의하고,
 * 셸의 로딩·시작·플레이·실패·종료 상태 전환을 시나리오별로 재현한다. 실제 게임 로직은 없다.
 *
 * 사용: stage-site.ps1 -Mock 으로 web/와 함께 taisei.js 이름으로 배치한 뒤 index.html?mock=<시나리오> 로 연다.
 *   ok(기본)      정상 로딩 → 첫 프레임 → 리소스 프리페치 진행 → 플레이 상태 유지
 *   reject        모듈 초기화(wasm 내려받기) 실패로 팩터리 Promise가 거부됨
 *   abort         Emscripten abort(onAbort 호출 후 RuntimeError throw)
 *   contract      인스턴스에 callMain이 없음(산출물 계약 불일치)
 *   nofactory     로더가 createTaisei를 정의하지 않음
 *   crash         첫 프레임 이후 비동기 예외(window error)
 *   exit          첫 프레임 이후 onExit(0)
 *   download-fail 수정 전 빌드처럼 로딩 중 리소스 내려받기 실패를 printErr 로그로만 알림
 *   asset-fatal   fork PR #1 계약: setStatus("Error: Failed to download …") 뒤 필수 리소스 누락으로 onAbort
 *   asset-optional fork PR #1 계약: 첫 프레임 뒤 선택 리소스 내려받기 실패를 setStatus("Error: …")로 알리고 계속 플레이
 *   slow          각 단계 지연을 길게 해 진행 표시를 눈으로 확인
 */
(function () {
    'use strict';

    var params = new URLSearchParams(window.location.search);
    var scenario = params.get('mock') || 'ok';
    var slow = scenario === 'slow';
    var stepDelay = slow ? 900 : 120;

    if (scenario === 'nofactory') {
        return;
    }

    function sleep(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    window.createTaisei = async function createTaisei(moduleArg) {
        var Module = moduleArg || {};
        var gl = Module.preinitializedWebGLContext;
        var canvas = Module.canvas;
        var print = Module.print || function () {};
        var printErr = Module.printErr || function () {};
        var setStatus = Module.setStatus || function () {};

        if (!gl || !canvas) {
            throw new Error('mock: Module.canvas 또는 Module.preinitializedWebGLContext가 없습니다.');
        }

        print('mock: createTaisei scenario=' + scenario);

        // preamble.js의 monitorRunDependencies와 같은 형식의 진행 메시지
        var total = 3;
        for (var i = 1; i <= total; i++) {
            await sleep(stepDelay);
            setStatus('Preparing… (' + i + '/' + total + ')');
        }
        await sleep(stepDelay);

        if (scenario === 'reject') {
            throw new Error('mock: failed to asynchronously prepare wasm: 404 : taisei.wasm');
        }
        if (scenario === 'abort') {
            if (Module.onAbort) Module.onAbort('mock: Cannot enlarge memory arrays');
            throw new WebAssembly.RuntimeError('Aborted(mock: Cannot enlarge memory arrays)');
        }
        if (scenario === 'download-fail') {
            // 수정 전 빌드는 log_error를 Module.print로 내보낸다(printErr가 아님).
            print('E: vfs/emscripten_fetch>fetch_onerror: Failed to download data/0123456789abcdef (status 404: Not Found)');
        }

        setStatus('All downloads complete.');

        if (scenario === 'asset-fatal') {
            // emscripten_fetch.c(fork PR #1): 포기 → setStatus("Error: …", true) → 필수 리소스면 log_fatal → abort
            await sleep(stepDelay);
            print('E: vfs/emscripten_fetch>vfs_fetch_open: Giving up on data/6e3e30da79a2d3206b95e99bcdcdd2e7a0e1a52f1ba75c9b03a89d0dd9012656 after 1 attempt(s); last HTTP status 404');
            setStatus('Error: Failed to download data/6e3e30da79a2d3206b95e99bcdcdd2e7a0e1a52f1ba75c9b03a89d0dd9012656 (HTTP status 404)', true);
            await sleep(stepDelay);
            print("F: resource>load_resource_finish: Required font 'standard_cjk' couldn't be loaded");
            if (Module.onAbort) Module.onAbort('Aborted()');
            throw new WebAssembly.RuntimeError('Aborted(). Build with -sASSERTIONS for more info.');
        }

        var running = false;
        var pressed = {};
        var hue = 0;
        var frames = 0;

        function frame() {
            if (!running) return;
            frames++;
            hue = (hue + 0.5) % 360;
            // 눌린 방향키에 따라 색을 바꿔 입력이 canvas에 도달하는지 눈으로 확인한다.
            var r = 0.1 + (pressed.ArrowLeft ? 0.6 : 0), g = 0.1 + (pressed.ArrowUp ? 0.6 : 0), b = 0.2 + (pressed.ArrowRight ? 0.6 : 0);
            if (pressed.ArrowDown) { r += 0.3; g += 0.3; }
            gl.viewport(0, 0, canvas.width, canvas.height);
            gl.clearColor(r, g, b, 1);
            gl.clear(gl.COLOR_BUFFER_BIT);
            gl.enable(gl.SCISSOR_TEST);
            // 가운데에 4:3 사각형을 그려 비율·크기 동기화를 확인한다.
            var w = canvas.width, h = canvas.height;
            var bw = Math.min(w, h * 4 / 3), bh = bw * 3 / 4;
            gl.scissor((w - bw) / 2, (h - bh) / 2, bw, bh);
            gl.clearColor(0.5 + 0.5 * Math.sin(hue / 30), 0.3, 0.6, 1);
            gl.clear(gl.COLOR_BUFFER_BIT);
            gl.disable(gl.SCISSOR_TEST);
            window.requestAnimationFrame(frame);
        }

        function onKeyDown(e) {
            if (!pressed[e.key]) print('mock: keydown ' + e.key + ' (defaultPrevented=' + e.defaultPrevented + ')');
            pressed[e.key] = true;
        }
        function onKeyUp(e) {
            delete pressed[e.key];
            print('mock: keyup ' + e.key);
        }
        function onBlur() {
            // SDL의 FOCUS_LOST 키 해제를 흉내 낸다.
            if (Object.keys(pressed).length) print('mock: blur -> release ' + Object.keys(pressed).join(','));
            pressed = {};
        }

        var instance = {
            mock: true,
            scenario: scenario,
            get frames() { return frames; },
            get pressed() { return Object.keys(pressed); },
            initFilesystem: function () {
                print('mock: initFilesystem (IDBFS mount 흉내)');
            },
            callMain: async function () {
                setStatus('Running...');
                running = true;
                // SDL은 window 단위로 키 이벤트를 받는다(bubble 단계).
                window.addEventListener('keydown', onKeyDown);
                window.addEventListener('keyup', onKeyUp);
                window.addEventListener('blur', onBlur);
                window.requestAnimationFrame(frame);
                await sleep(stepDelay * 2);
                setStatus('');
                if (Module.onFirstFrame) Module.onFirstFrame();
                print('mock: first frame');

                if (scenario === 'crash') {
                    setTimeout(function () { throw new Error('mock: RuntimeError: memory access out of bounds'); }, stepDelay * 3);
                    return;
                }
                if (scenario === 'exit') {
                    setTimeout(function () {
                        running = false;
                        if (Module.onExit) Module.onExit(0);
                    }, stepDelay * 5);
                    return;
                }
                if (scenario === 'asset-optional') {
                    // 선택 리소스 실패: 런타임은 경고만 남기고 계속 진행한다. 이후 상태 갱신이 경고를 덮지 않아야 한다.
                    await sleep(stepDelay * 2);
                    setStatus('Error: Failed to download data/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef (HTTP status 404)', true);
                    print('W: resource>load_resource_finish: optional texture could not be loaded; continuing');
                    for (var j = 0; j <= 10; j++) {
                        await sleep(80);
                        setStatus(j >= 10 ? '' : 'Prefetching resources… (' + j + '/10)', true);
                    }
                    print('mock: continuing after optional asset failure');
                    return;
                }
                // emscripten_fetch.c의 update_dl_status와 같은 형식의 프리페치 진행
                var n = slow ? 12 : 20;
                for (var i = 0; i <= n; i++) {
                    await sleep(slow ? 400 : 60);
                    setStatus(i >= n ? '' : 'Prefetching resources… (' + i + '/' + n + ')', true);
                }
                print('mock: prefetch complete');
            },
        };

        if (scenario === 'contract') {
            delete instance.callMain;
        }
        return instance;
    };
})();
