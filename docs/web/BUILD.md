# Taisei 웹 빌드와 패키징

담당: 세션 1 ([#4](https://github.com/kthss01/mini-danmaku-ai-claude/issues/4)) · 부모: [#2](https://github.com/kthss01/mini-danmaku-ai-claude/issues/2)
검증일: 2026-10-23 · 대상: Windows 11 x64 + Docker Desktop

이 문서는 웹 산출물을 만드는 방법과 산출물 계약만 다룬다. 실제 플레이 검증과 최종 실행 안내는 세션 5의 통합 문서가 담당한다.

## 고정 도구

공식 CI(`game/taisei/.github/workflows/main.yml`의 `emscripten-test-build`)와 같은 조합을 사용한다.

| 항목 | 값 |
| --- | --- |
| Taisei 커밋 | `5668c41b41f7227d21fc80cf56997d4d30356ce7` (submodule 고정값) |
| 빌드 이미지 | `taiseiproject/linux-toolkit:20260804@sha256:1104b4a5bba4d7f03f7d03cd6990571b476afe276c97d9d8074c33b1834474b2` |
| emsdk / Emscripten | `5.0.3` (emsdk 태그 `5.0.3`로 clone) |
| Meson cross-file | `misc/ci/common-options.ini`, `misc/ci/forcefallback.ini`, `configs/web-build/emscripten-toolchain.ini`, `misc/ci/emscripten-build.ini` |
| 추가 옵션 | `-Dbuild.cpp_std=gnu++14` (공식 CI와 동일) |

emsdk 설치본은 Docker named volume `taisei-emsdk-5.0.3`에 캐시한다. 처음 한 번은 emsdk와 LLVM 툴체인을 내려받으므로 시간이 더 걸린다.

## 명령

저장소 루트의 Windows PowerShell에서 실행한다. Docker Desktop이 실행 중이어야 한다.

```powershell
git clone --recurse-submodules https://github.com/kthss01/mini-danmaku-ai-claude.git
Set-Location mini-danmaku-ai-claude
.\scripts\setup-taisei.ps1
.\scripts\build-web.ps1
```

| 옵션 | 동작 |
| --- | --- |
| (없음) | 컴파일·`meson install` 후 사이트 패키징. `build/web/install`이 이미 있으면 중단 |
| `-Force` | 기존 `build/web/install`을 지우고 다시 컴파일 |
| `-PackageOnly` | 컴파일 없이 기존 `build/web/install`로 `build/web/site`만 다시 구성 |

`build/web/site`는 실행할 때마다 새로 만든다. `build/`는 `.gitignore`로 제외되어 산출물이 커밋되지 않는다.

스크립트는 다음 순서로 동작한다.

1. `configs/web-build/container-build.sh`를 LF로 정규화해 `build/web/.container-build.sh`에 쓴다.
2. 컨테이너에서 emsdk를 설치·활성화하고, `game/taisei`를 LF로 다시 checkout해 Meson으로 빌드한다.
3. `meson install` 결과를 `build/web/install`에 둔다.
4. `build/web/site`를 구성하고 필수 파일(`taisei.html`, `taisei.js`, `taisei.wasm`, `data/`)이 없으면 실패한다.

## 산출물 계약

```text
build/web/
├── install/              # meson install 원본 (중간 산출물)
└── site/                 # 최종 서빙 루트
    ├── (web/의 정적 셸 파일, web/game/ 제외)   # 세션 3
    ├── COPYING.txt
    ├── build-info.json   # 커밋·도구 버전·파일 수·총 용량
    └── game/
        ├── taisei.html   # 업스트림 셸 (createTaisei 호출)
        ├── taisei.js     # MODULARIZE 로더, 전역 createTaisei
        ├── taisei.wasm
        ├── data/         # 콘텐츠 주소 리소스 (파일명 = SHA-256)
        ├── background.webp, scythe.webp, favicon.ico
        ├── COPYING.txt
        └── GAME*.html, ENVIRON*.html, STORY*.txt, README.txt
```

- `web/`가 있으면 `web/game/`을 제외한 파일을 `site/` 루트로, `web/game/` 아래 파일을 `site/game/`으로 덮어쓴다.
- `web/`가 없으면 업스트림 게임 셸만 패키징하고 그 사실을 출력한다.
- 게임 진입 URL은 서빙 루트 기준 `game/taisei.html`이다.

### 로더 제약

- 리소스 인덱스는 wasm에 내장되고, 실행 중 `emscripten_fetch`로 `data/<sha256>`을 요청한다.
- 이 URL은 실행 중인 **HTML 문서 기준** 상대 경로다. `locateFile`은 `taisei.wasm`에만 적용된다.
- 따라서 `createTaisei`를 호출하는 페이지는 `data/`와 같은 디렉터리, 즉 `site/game/`에 있어야 한다.
- 로더는 셸이 만든 WebGL 2 컨텍스트(`preinitializedWebGLContext`)를 받아야 한다. 호출 순서는 `await createTaisei(module)` → `module.initFilesystem()` → `module.callMain()`이다.
- 저장 데이터는 IDBFS(`/persistent`)에 기록된다.

### 서빙 요구사항 (세션 4 참고)

- `.wasm`은 `application/wasm`으로 제공한다.
- `data/` 파일은 확장자가 없다. 로더가 MIME을 `application/octet-stream`으로 덮어쓰므로 서버 MIME은 영향이 없다.
- pthreads가 비활성이라 COOP/COEP 헤더는 필요 없다.
- 브라우저 요구사항: WebGL 2, wasm SIMD128·bulk memory (`MIN_CHROME_VERSION=91`, `MIN_FIREFOX_VERSION=89`).

## 검증 결과

### 깨끗한 clone 재현

새 디렉터리에 `git clone --recurse-submodules`로 받은 뒤 `.\scripts\build-web.ps1`을 실행했다. emsdk는 이전 실행에서 채운 named volume을 재사용했다.

| 항목 | 결과 |
| --- | --- |
| 종료 코드 | 0 |
| 소요 시간 | 약 4분 (emsdk 캐시 사용 시) |
| `site/` 파일 수 | 544 (`build-info.json` 제외, `web/` 없음) |
| `site/` 총 용량 | 222,368,405 바이트 (약 212 MiB) |
| `data/` 파일 수 | 529 |

주요 파일 크기와 SHA-256:

| 파일 | 크기 (바이트) | SHA-256 |
| --- | --- | --- |
| `game/taisei.wasm` | 4,538,726 | `68e8638c5a6219c09880e2efcf9e7390a9258ab985ef6376c24af131319fd353` |
| `game/taisei.js` | 100,933 | `3e7ed5b785d039c22c67bb87a70b36ee01d3b96202ff715643d7e97eb33c8d64` |
| `game/taisei.html` | 12,168 | `113240a898a555b79b8dcfa49c75fe5aa89a68831c377431347e8127ca3ac555` |

같은 커밋으로 다른 작업 폴더에서 한 번 더 빌드해 비교했다.

- `taisei.js`와 `data/` 파일 이름 529개는 동일했다.
- `taisei.wasm`은 크기는 같지만 해시가 달랐다. 바이트 단위 재현성은 보장하지 않는 것으로 기록한다.

### 스크립트 동작 확인

- `-PackageOnly`: 컴파일 없이 `site`를 다시 구성했다. 로컬 서버가 `site`를 제공하는 중에도 동작한다.
- 옵션 없이 다시 실행하면 `build/web/install already exists` 오류로 중단되어 기존 결과를 덮어쓰지 않는다.
- 임시 `web/index.html`, `web/game/overlay.txt`로 패키징하면 각각 `site/index.html`, `site/game/overlay.txt`에 배치되고 `site/game/index.html`, `site/overlay.txt`는 생기지 않았다.

### 브라우저 로딩 확인 (스모크 테스트)

`build/web/site`를 `python -m http.server 8761 --bind 127.0.0.1`로 제공하고 Claude 데스크톱 앱 내장 Chromium 브라우저에서 `http://127.0.0.1:8761/game/taisei.html`을 열었다.

- 로딩 진행률 표시 후 게임이 시작되어 첫 장면이 렌더링되고 창 제목이 `Taisei Project v1.5-dev`로 바뀌었다.
- 약 25초 동안 리소스 요청 250건 중 `data/` 요청 246건이 모두 `/game/data/` 경로로 나갔고 400 이상 응답은 없었다.
- 게임 로그의 오류 항목은 다음과 같다. 처음 세 항목은 첫 실행의 정상 메시지이고, `global.pp`는 Windows 빌드에서도 같은 메시지가 나온다.
  - `storage/config`, `progress.zst` 없음 (첫 실행)
  - `SDL_CreateSemaphore() failed: SDL not built with thread support` (웹 빌드는 스레드 비활성)
  - `res/shader/global.pp` 없음 → 후처리 파이프라인 `global` 로드 실패

키 입력, 스테이지 진입, 오디오, 저장·리플레이는 이 문서의 검증 범위가 아니다. 세션 2·5가 검증한다.

## 제약과 남은 문제

- 첫 실행 시 리소스 약 209 MiB를 내려받는다. 이후 IDBFS 캐시를 사용한다.
- wasm 바이트 단위 재현성은 확인되지 않았다.
- `res/shader/global.pp` 누락 메시지의 영향은 세션 2에서 확인이 필요하다.
- 업스트림 셸 문구는 영어이며 "실험적(Experimental)" 경고를 표시한다. 한국어 안내는 세션 3의 `web/` 셸이 담당한다.
- macOS·Linux 호스트용 빌드 스크립트는 제공하지 않는다. `configs/web-build/container-build.sh`는 같은 이미지에서 그대로 사용할 수 있다.
