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
 *   download-fail 로딩 중 리소스 내려받기 실패 메시지(printErr) 재현
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
            printErr('Failed to download data/0123456789abcdef (status 404: Not Found)');
        }

        setStatus('All downloads complete.');

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
