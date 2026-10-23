// fixture loader: 실제 Emscripten 출력 대신 .wasm 참조 문자열만 흉내 낸다.
var createGame = function () {
    var wasmPath = "game.wasm";
    var threads = false;
    return fetch(new URL(wasmPath, document.currentScript.src)).then(function (r) { return r.arrayBuffer(); });
};
