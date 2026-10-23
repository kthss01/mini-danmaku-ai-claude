"""서버·검사 도구 테스트용 소형 fixture 산출물을 생성한다.

실제 Taisei 빌드와 같은 구조(진입 index.html, game/ 하위에 HTML·JS·WASM, 해시 이름 리소스 data/)를
아주 작은 파일로 흉내 낸다. 실제 게임 산출물 검증을 대신하지 않는다.

    python tests/web-server/make_fixture.py            # tests/web-server/fixture/site 재생성
    python tests/web-server/make_fixture.py <dest>     # 다른 위치에 생성
"""

from __future__ import annotations

import hashlib
import shutil
import struct
import sys
import zlib
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixture" / "site"


def _leb128(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _section(section_id: int, body: bytes) -> bytes:
    return bytes([section_id]) + _leb128(len(body)) + body


def make_wasm(shared_memory: bool = False, data_dir: str = "data") -> bytes:
    """메모리 섹션과 '<data_dir>/%s' 문자열을 담은 data 섹션만 있는 최소 WASM 모듈."""
    if shared_memory:
        memory = _leb128(1) + bytes([0x03]) + _leb128(1) + _leb128(1)  # flags: has-max | shared
    else:
        memory = _leb128(1) + bytes([0x00]) + _leb128(1)
    payload = f"{data_dir}/%s\0".encode()
    segment = bytes([0x00]) + bytes([0x41, 0x00, 0x0B]) + _leb128(len(payload)) + payload
    data = _leb128(1) + segment
    return b"\0asm\x01\x00\x00\x00" + _section(5, memory) + _section(11, data)


def make_png() -> bytes:
    """1×1 투명 PNG."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
    <meta charset="utf-8">
    <title>fixture shell</title>
    <link rel="stylesheet" href="style.css">
    <link rel="icon" type="image/png" href="img/bg.png">
</head>
<body>
    <h1>fixture</h1>
    <a id="start" href="game/game.html">start</a>
    <a href="COPYING.txt">license</a>
    <a href="https://example.invalid/external">external link (ignored)</a>
</body>
</html>
"""

GAME_HTML = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>fixture game</title>
    <link rel="preload" href="game.wasm" as="fetch" crossorigin>
    <script id="game-script" src="game.js" async></script>
    <style>body { background: url('../img/bg.png'); }</style>
</head>
<body>
    <canvas id="canvas"></canvas>
    <!--<script src="debug-only-not-shipped.js"></script>-->
</body>
</html>
"""

GAME_JS_TEMPLATE = """// fixture loader: 실제 Emscripten 출력 대신 .wasm 참조 문자열만 흉내 낸다.
var createGame = function () {{
    var wasmPath = "game.wasm";
    {marker}
    return fetch(new URL(wasmPath, document.currentScript.src)).then(function (r) {{ return r.arrayBuffer(); }});
}};
"""

STYLE_CSS = "body { margin: 0; background: #111 url('img/bg.png') no-repeat; }\n"
COPYING = "fixture license text\n"
RESOURCES = (b"fixture resource A\n", b"fixture resource B\n")


def build_fixture(dest: Path, shared_memory: bool = False) -> Path:
    """dest 에 fixture 사이트를 만든다. 이미 있으면 지우고 다시 만든다."""
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "game" / "data").mkdir(parents=True)
    (dest / "img").mkdir()
    (dest / "index.html").write_text(INDEX_HTML, encoding="utf-8", newline="\n")
    (dest / "style.css").write_text(STYLE_CSS, encoding="utf-8", newline="\n")
    (dest / "COPYING.txt").write_text(COPYING, encoding="utf-8", newline="\n")
    (dest / "img" / "bg.png").write_bytes(make_png())
    (dest / "game" / "game.html").write_text(GAME_HTML, encoding="utf-8", newline="\n")
    marker = "var threads = typeof SharedArrayBuffer !== 'undefined';" if shared_memory else "var threads = false;"
    (dest / "game" / "game.js").write_text(GAME_JS_TEMPLATE.format(marker=marker), encoding="utf-8", newline="\n")
    (dest / "game" / "game.wasm").write_bytes(make_wasm(shared_memory=shared_memory))
    for content in RESOURCES:
        (dest / "game" / "data" / hashlib.sha256(content).hexdigest()).write_bytes(content)
    return dest


def main(argv: list[str]) -> int:
    dest = Path(argv[1]).resolve() if len(argv) > 1 else FIXTURE_DIR
    build_fixture(dest)
    print(f"fixture 생성: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
