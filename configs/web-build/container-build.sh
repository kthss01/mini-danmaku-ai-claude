#!/bin/sh
# Taisei Emscripten 빌드 컨테이너 내부 스크립트.
# scripts/build-web.ps1이 LF로 정규화해 실행한다. 직접 실행하지 않는다.
#
# 필요한 환경 변수:
#   EM_VERSION      emsdk/Emscripten 버전 (공식 CI의 EM_VERSION과 일치)
#   TAISEI_COMMIT   빌드할 game/taisei 커밋 (40자리)
#   INSTALL_PREFIX  meson install 대상 (컨테이너 경로)
set -eu

: "${EM_VERSION:?}"
: "${TAISEI_COMMIT:?}"
: "${INSTALL_PREFIX:?}"

EMSDK_DIR=/opt/emsdk
CONFIG_DIR=/workspace/configs/web-build

# emsdk는 named volume에 캐시한다. 처음이면 버전 태그로 고정 clone한다.
if [ ! -x "$EMSDK_DIR/emsdk" ]; then
    git clone --depth 1 --branch "$EM_VERSION" https://github.com/emscripten-core/emsdk.git /tmp/emsdk-src
    cp -a /tmp/emsdk-src/. "$EMSDK_DIR/"
fi
"$EMSDK_DIR/emsdk" install "$EM_VERSION"
"$EMSDK_DIR/emsdk" activate "$EM_VERSION"
. "$EMSDK_DIR/emsdk_env.sh"
emcc -v

# Windows CRLF 체크아웃의 영향을 받지 않도록 컨테이너 안에서 LF로 다시 checkout한다.
git clone --recurse-submodules --no-local /workspace/game/taisei /tmp/taisei
cd /tmp/taisei
git checkout "$TAISEI_COMMIT"
git submodule update --init --recursive

meson setup build/web \
    --cross-file misc/ci/common-options.ini \
    --cross-file misc/ci/forcefallback.ini \
    --cross-file "$CONFIG_DIR/emscripten-toolchain.ini" \
    --cross-file misc/ci/emscripten-build.ini \
    --prefix="$INSTALL_PREFIX" \
    -Dbuild.cpp_std=gnu++14
meson compile -C build/web
meson install -C build/web
