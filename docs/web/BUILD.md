# Taisei 웹 빌드와 패키징

담당: 세션 1 ([#4](https://github.com/kthss01/mini-danmaku-ai-claude/issues/4)) · 부모: [#2](https://github.com/kthss01/mini-danmaku-ai-claude/issues/2)
검증일: 2026-10-23 · 대상: Windows 11 x64 + Docker Desktop

이 문서는 웹 산출물을 만드는 방법과 산출물 계약만 다룬다. 실제 플레이 검증과 최종 실행 안내는 세션 5의 통합 문서가 담당한다.

## 고정 도구

공식 CI(`game/taisei/.github/workflows/main.yml`의 `emscripten-test-build`)와 같은 조합을 사용한다.

| 항목 | 값 |
| --- | --- |
| Taisei 커밋 | `84b414f7…` (submodule 고정값 — 전체 해시는 `git ls-tree HEAD game/taisei`. fork PR kthss01/taisei#3 머지 커밋: 웹 빌드에서 자동 발사(Shoot by default)를 기본으로 켬. 앞선 fork PR #4(`cc3de0e0`): 한국어(`ko`) 번역 추가, [L10N.md](L10N.md). 앞선 fork PR #2(`1d4b468d`): 인트로 프롤로그를 첫 시청에도 Esc로 건너뛰기. 앞선 fork PR #1(`f59212b7`): 리소스 내려받기 실패 시 오류로 중단, [RUNTIME.md](RUNTIME.md) 4장) |
| 빌드 이미지 | `taiseiproject/linux-toolkit:20260804@sha256:1104b4a5bba4d7f03f7d03cd6990571b476afe276c97d9d8074c33b1834474b2` |
| emsdk / Emscripten | `5.0.3` (emsdk 태그 `5.0.3`로 clone) |
| Meson cross-file | `misc/ci/common-options.ini`, `misc/ci/forcefallback.ini`, `configs/web-build/emscripten-toolchain.ini`, `misc/ci/emscripten-build.ini` |
| 추가 옵션 | `-Dbuild.cpp_std=gnu++14` (공식 CI와 동일) |

이전 고정값은 `5668c41b41f7227d21fc80cf56997d4d30356ce7`(업스트림 `master`)이다. 아래 "검증 결과"의 앞 절들은 당시 커밋으로 만든 증거이며 그대로 둔다.

emsdk 설치본은 Docker named volume `taisei-emsdk-5.0.3`에 캐시한다. 처음 한 번은 emsdk와 LLVM 툴체인을 내려받으므로 시간이 더 걸린다.

## 명령

저장소 루트의 Windows PowerShell에서 실행한다. Docker Desktop이 실행 중이어야 한다.

```powershell
git clone --recurse-submodules https://github.com/kthss01/mini-danmaku-ai-claude.git
Set-Location mini-danmaku-ai-claude
.\scripts\setup-taisei.ps1
.\scripts\build-web.ps1
```

`setup-taisei.ps1`은 Taisei 추적 파일 중 줄바꿈만 다른 파일을 커밋과 같은 LF로 맞춘다(조건과 안전 장치는 [SETUP.md](../SETUP.md)). 이 단계를 건너뛰었거나, 이전 버전으로 설정했거나, 안전 조건 때문에 정리를 건너뛴 clone은 줄바꿈 차이 때문에 `build.repositoryDirtyEntries`에 ` M game/taisei`가 기록될 수 있다. 컴파일은 컨테이너 안에서 커밋 기준으로 다시 checkout하므로 산출물에는 영향이 없지만, 깨끗한 checkout 재현 근거가 되려면 `git status --porcelain`이 비어 있어야 한다.

| 옵션 | 동작 |
| --- | --- |
| (없음) | 컴파일·`meson install` 후 사이트 패키징. `build/web/install`이 이미 있으면 중단 |
| `-Force` | 기존 `build/web/install`을 지우고 다시 컴파일 |
| `-PackageOnly` | 컴파일 없이 기존 `build/web/install`로 `build/web/site`만 다시 구성. `install-provenance.json`이 없거나 install 파일 해시가 기록과 다르면 거부 |

`build/web/site`는 실행할 때마다 새로 만든다. `build/`는 `.gitignore`로 제외되어 산출물이 커밋되지 않는다.

스크립트는 다음 순서로 동작한다.

1. `configs/web-build/container-build.sh`를 LF로 정규화해 `build/web/.container-build.sh`에 쓴다.
2. 컨테이너에서 emsdk를 설치·활성화하고, `game/taisei`를 LF로 다시 checkout해 Meson으로 빌드한다.
3. `meson install` 결과를 `build/web/install`에 두고, 컴파일 성공 시에만 `build/web/install-provenance.json`에 빌드 출처(`data/` 전체 목록 포함)를 기록한다.
4. 출처 기록과 install의 `taisei.html`, `taisei.js`, `taisei.wasm`, `COPYING.txt` 해시, 그리고 `data/` 전체 목록·크기·해시가 일치하는지 확인한다. 실패하면 기존 `site/`를 보존한다.
5. `build/web/site`를 구성하고 필수 파일이 없으면 실패한다. `build-info.json`에 빌드 출처와 이번 패키징 정보를 분리해 기록한다.

### AI 어댑터·정책 패키징

`ai/bridge/taisei-ai-bridge.mjs`와 `ai/policies/**`가 있으면 `site/game/ai/bridge/`, `site/game/ai/policies/**`로 복사하고 `build-info.json`의 `packaging.aiPackaged`·`aiDirtyEntries`·`aiSha256`에 기록한다(릴리스·개발자 빌드 공통). 세부는 [docs/ai/RUNNER.md](../ai/RUNNER.md) 11절.

### 개발자 빌드 (AI 실험용)

`-Flavor developer`는 같은 절차를 `build/web-dev/`에 `-Ddeveloper=true`로 실행한다. 릴리스 산출물(`build/web/**`)과 출처 기록은 바꾸지 않는다. `build-info.json`의 `build`에 `flavor`, `mesonOptions`, `rulesPreserved`(개발자 빌드는 검증 전까지 `unverified`)가 기록된다. 자세한 계약과 사용은 [docs/ai/RUNNER.md](../ai/RUNNER.md)를 본다. `git worktree`로 만든 작업 폴더에서는 `game/taisei/.git`이 컨테이너 밖을 가리켜 Docker 빌드가 실패하므로 일반 clone에서 빌드한다.

### 빌드 출처와 패키징 정보

`-PackageOnly`는 컴파일하지 않은 바이너리를 현재 HEAD의 빌드로 기록하면 안 되므로 두 기록을 분리한다.

| 파일 | 기록 시점 | 내용 |
| --- | --- | --- |
| `build/web/install-provenance.json` | 컴파일 성공 시 | 빌드 시작·종료 시각(UTC), Taisei 커밋, 메인 커밋, 양쪽 작업 트리의 미커밋 변경 목록, 빌드 입력 파일 해시, emsdk 버전, 이미지, install 파일 SHA-256, `data/` 전체 목록(파일별 크기·SHA-256)과 파일 수·총 용량 |
| `build/web/site/build-info.json` | 패키징할 때마다 | `build`(위 출처 기록 그대로), `packaging`(패키징 시각, 모드, 현재 메인 커밋, 미커밋 변경, `web/` 존재 여부·변경·복사한 셸 파일 전체 SHA-256), `site`(진입 URL, 파일 수, 용량, 주요 파일 SHA-256) |

- 출처 기록이 없거나 `data/` 목록이 없는 install(이 변경 이전에 만든 것 포함)은 패키징을 거부한다. `-Force`로 다시 빌드한다.
- 패키징 전 검사는 기존 `site/`를 지우기 전에 수행한다. 검사에 실패하면 기존 `site/`는 그대로 남는다.
- 라이선스 고지는 현재 작업 트리가 아니라 install에 포함된 그 빌드의 `COPYING.txt`를 복사한다.
- `build.buildStartedAtUtc`가 실제 빌드 시각이다. 파일 수정 시각은 복사 시점이므로 빌드 시각으로 쓰지 않는다.

### `data/` 무결성 검사

- 빌드 시 `data/` 파일 529개의 이름·크기·SHA-256을 모두 출처 기록에 저장한다. 파일 이름이 내용의 SHA-256과 같은 콘텐츠 주소 방식이지만(`dataContentAddressed`로 기록), 검사는 이름에 의존하지 않고 저장한 해시와 비교한다.
- 패키징 전(`-PackageOnly` 포함) `data/`가 디렉터리인지, 누락·추가 파일이 없는지, 파일별 크기와 SHA-256이 기록과 같은지 확인한다. 하나라도 다르면 실패하고 `site/`를 건드리지 않는다.
- 비용: 정상 패키징 때마다 약 207 MiB를 모두 읽어 해시한다. 이 PC에서 `-PackageOnly` 전체(검사·복사·기록 포함)가 약 10초 걸렸다. 크기·이름만 비교하는 방식은 내용 변조를 잡지 못하므로 채택하지 않았다.
- 폴더·파일 누락과 추가는 해시 계산 전에 목록 비교로 먼저 걸러진다.

### 진입점과 셸 해시

- `site/game/index.html`(세션 3의 `web/game/` 셸)이 있으면 `site.entry`를 `game/index.html`로, 없으면 업스트림 셸 `game/taisei.html`로 기록한다.
- `site.sha256`에는 `index.html`, `COPYING.txt`, `game/index.html`, `game/shell.js`, `game/shell.css`, `game/shell-config.js`, `game/taisei.html`, `game/taisei.js`, `game/taisei.wasm`, `game/COPYING.txt` 중 존재하는 파일의 해시를 기록한다.
- `packaging.webShellSha256`에는 `web/`에서 복사한 모든 파일의 해시를 상대 경로별로 기록한다. `web/`와 `site/`의 상대 경로가 같으므로 미커밋 `web/game/` 내용도 특정할 수 있다.

## 산출물 계약

```text
build/web/
├── install/                  # meson install 원본 (중간 산출물)
├── install-provenance.json   # install을 만든 빌드의 출처 (컴파일 성공 시에만 기록)
└── site/                     # 최종 서빙 루트
    ├── (web/의 정적 셸 파일, web/game/ 제외)   # 세션 3
    ├── COPYING.txt           # 해당 빌드 install의 고지
    ├── build-info.json       # build: 빌드 출처 / packaging: 패키징 정보 / site: 파일 해시
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
- 게임 진입 URL은 서빙 루트 기준 `game/index.html`(세션 3 셸이 있을 때) 또는 `game/taisei.html`(업스트림 셸만 있을 때)이다. 실제 값은 `build-info.json`의 `site.entry`에 기록된다.
- 루트 셸이 없을 때 서버의 기본 문서 옵션으로 `game/`을 다시 붙이면 `game/game/` 경로가 된다. 이 경우 서빙 루트를 `build/web/site`로 두고 `/game/taisei.html`을 직접 연다.

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

### 공식 빌드 (Taisei `f59212b7`, 메인 `797f880`, 최신)

gitlink 갱신 커밋 `797f880`을 만든 뒤 작업 트리에 미커밋 변경이 없는 상태에서 `.\scripts\build-web.ps1 -Force`로 빌드했다. main에 머지된 세션 3 셸(`web/`)이 함께 패키징됐다. 이후 커밋은 이 절을 기록한 문서 변경뿐이며 빌드 입력 파일은 바뀌지 않았다.

| 항목 | 결과 |
| --- | --- |
| 종료 코드 | 0 |
| 소요 시간 | 4분 31초 (emsdk 캐시 사용) |
| `build.taiseiCommit` | `f59212b72df3b68459b4677a6200e42be700078a` |
| `build.repositoryCommit` | `797f88000b67b88c9f583bbff3e64648fc13d9e7` |
| 미커밋 변경 (메인·Taisei·`web/`) | 없음 |
| 빌드 시각(UTC) | 시작 `2026-10-23T12:31:22Z`, 종료 `2026-10-23T12:35:37Z` |
| `site.entry` | `game/index.html` |
| `site/` 파일 수 | 549 (`build-info.json` 제외) |
| `site/` 총 용량 | 222,408,181 바이트 (`build-info.json` 제외) |
| `data/` | 529개, 217,186,447 바이트 (`5668c41b` 빌드와 같은 목록) |

| 파일 | 크기 (바이트) | SHA-256 |
| --- | --- | --- |
| `game/taisei.wasm` | 4,539,198 | `76f6b39da5aa417fd41c7cbfb59da4216df0e7a3f1f02feb3c8be97fd1826192` |
| `game/taisei.js` | 101,107 | `d49ca968c16d0a69cc275f21a2f537db51c151a25401781c911149c328c73a01` |
| `game/taisei.html` | 12,168 | `113240a898a555b79b8dcfa49c75fe5aa89a68831c377431347e8127ca3ac555` |
| `index.html` | - | `f0728725fe9680f3d19832f9693e6bb9a1a279d5c822cf5f58fbc10c68626b16` |
| `game/index.html` | - | `0a8b31f86be3f7b53cce0d3ae88d7d49ea5ac02e5c652597ab4d439596c08f2d` |
| `game/shell.js` | - | `aee98beb3689e41ba1bbe20ed10524034651b3271ad411a559403d908f8c8d57` |
| `COPYING.txt` | 2,529 | `507ba6eaceaf6fd923246480f53932b25a1ebbb25b2dd19c4f37bfc5fc83795a` |

`taisei.js`와 `taisei.wasm`은 fork 수정이 반영되어 `5668c41b` 빌드보다 커졌다. 전체 해시 목록은 `build/web/site/build-info.json`에 있다.

서빙·자산 검사(세션 4 도구, `python scripts/serve-web.py --port 8762`):

| 검사 명령 진입 | 결과 |
| --- | --- |
| `--entry game/taisei.html --verify-hashes --sample-data -1` | 통과. 오류 0, 경고 0. HTTP 539건 실패 0. `taisei.wasm` 유효(섹션 11개), `data/` 529개 내용 해시 일치 |
| 기본 진입(`index.html`), `--entry game/index.html` | 통과(오류 0). 세션 3 셸이 `taisei.js`를 동적으로 불러와 도구가 wasm 참조를 추적하지 못해 `no-wasm` 경고 1건 |

브라우저 진입 확인(Claude 데스크톱 앱 내장 Chromium, 빈 IndexedDB 포트):

- `http://127.0.0.1:8762/` → `game/index.html`로 이동, `window.taiseiShell.state`는 `ready`
- "게임 시작" 클릭 후 약 20초 시점: `state=playing`, `hadFirstFrame=true`, `downloadErrors`·셸 `errors` 없음
- `game/taisei.wasm` 200, `data/` 요청 244건 모두 `/game/data/`, 400 이상 응답 없음

조작·오디오·저장과 실제 Chrome/Edge 검증은 세션 5의 공식 QA 범위다.

### 깨끗한 clone 재현 (Taisei `5668c41b`)

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

위 표는 출처 기록을 도입하기 전 스크립트(메인 커밋 `f3b52f1`)로 만든 결과다.

### 출처·`data/` 기록 도입 후 재빌드 (Taisei `5668c41b`)

같은 clone에서 `.\scripts\build-web.ps1 -Force`로 다시 컴파일했다. 메인 커밋 `d5f0bbd`에 `scripts/build-web.ps1`, `docs/web/BUILD.md` 미커밋 수정이 있는 상태였고, 출처 기록에 그 사실이 남았다.

| 항목 | 결과 |
| --- | --- |
| 종료 코드 | 0 |
| 소요 시간 | 4분 7초 (emsdk 캐시 사용) |
| 빌드 시각(UTC) | 시작 `2026-10-23T12:14:42Z`, 종료 `2026-10-23T12:18:32Z` |
| `site/` 파일 수 | 544 (`build-info.json` 제외, `web/` 없음) |
| `site/` 총 용량 | 222,368,303 바이트 (`build-info.json` 제외) |
| `data/` | 529개, 217,186,447 바이트, 콘텐츠 주소 일치(`dataContentAddressed=true`) |

| 파일 | 크기 (바이트) | SHA-256 |
| --- | --- | --- |
| `game/taisei.wasm` | 4,538,726 | `26ce2883419ad0f0b3e055c96108c80eb510abe3a905d6689c78efddb2067b64` |
| `game/taisei.js` | 100,933 | `3e7ed5b785d039c22c67bb87a70b36ee01d3b96202ff715643d7e97eb33c8d64` |
| `game/taisei.html` | 12,168 | `113240a898a555b79b8dcfa49c75fe5aa89a68831c377431347e8127ca3ac555` |
| `COPYING.txt` | 2,529 | `507ba6eaceaf6fd923246480f53932b25a1ebbb25b2dd19c4f37bfc5fc83795a` |

같은 Taisei 커밋으로 네 번 빌드한 결과를 비교하면 `taisei.js`, `taisei.html`, `data/` 파일 이름 529개는 모두 같았고, `taisei.wasm`만 크기는 같은데 해시가 매번 달랐다(`eb97b68b…`, `68e8638c…`, `239e0380…`, `26ce2883…`). 바이트 단위 재현성은 보장하지 않는 것으로 기록한다.

### 스크립트 동작 확인

- 옵션 없이 다시 실행하면 `build/web/install already exists` 오류로 중단되어 기존 결과를 덮어쓰지 않는다.
- `-PackageOnly`: 컴파일 없이 `site`를 다시 구성했다. 로컬 서버가 `site`를 제공하는 중에도 동작한다.
- 임시 `web/index.html`, `web/game/overlay.txt`로 패키징하면 각각 `site/index.html`, `site/game/overlay.txt`에 배치되고 `site/game/index.html`, `site/overlay.txt`는 생기지 않았다.

출처 기록 시나리오(모두 이 clone에서 수행):

| 시나리오 | 결과 |
| --- | --- |
| 출처 기록 없는 기존 install에 `-PackageOnly` | `install-provenance.json is missing … Rebuild with -Force` 오류로 거부 |
| 메인 커밋 `f3b52f1`에서 빌드 → 스크립트 커밋 `dad358e`로 HEAD 변경 + 임시 `web/` 추가 → `-PackageOnly` | 성공. `build.repositoryCommit`은 `f3b52f1` 유지, `packaging.repositoryCommit`은 `dad358e`, `packaging.mode`는 `PackageOnly`, `webShellDirtyEntries`에 `?? web/` 기록. `install-provenance.json` 해시 불변 |
| `install/taisei.html` 끝에 주석 추가 후 `-PackageOnly` | `does not match install-provenance.json` 오류로 거부 |
| 원본 복원·`web/` 삭제 후 `-PackageOnly` | 성공. 544개 파일, 222,368,303바이트 |

`data/` 무결성 시나리오(최신 재빌드 후 이 clone에서 수행). 각 시나리오 뒤 원상 복구했고, "site 보존"은 `site/` 파일 수와 `build-info.json` 해시가 실행 전후 같았다는 뜻이다.

| 시나리오 | 결과 |
| --- | --- |
| `data/` 이전 형식(목록 없음) 출처 기록 + `-PackageOnly` | 거부 |
| `install/data` 폴더 이름 변경(누락) | `data is missing or is not a directory`로 거부, site 보존 |
| `data/` 파일 1개 이동(누락) | `missing 1`로 거부, site 보존 |
| `data/` 파일 1개 첫 바이트 반전(이름·크기 동일) | `content differs`로 거부, site 보존 |
| 기록에 없는 `data/deadbeef` 추가 | `unexpected 1`로 거부, site 보존 |
| 원상 복구 후 `-PackageOnly` | 성공, 약 10초 |
| 임시 `web/index.html`, `web/game/index.html`, `shell.js`, `shell.css`, `shell-config.js` 추가 후 `-PackageOnly` | 성공. `site.entry=game/index.html`, `site.sha256`에 셸 4개 포함, `packaging.webShellSha256`에 `web/` 파일 5개 기록 |
| `web/` 삭제 후 `-PackageOnly` | 성공. `site.entry=game/taisei.html`로 복귀 |

### 브라우저 로딩 확인 (스모크 테스트, Taisei `5668c41b`)

`build/web/site`를 `python -m http.server 8761 --bind 127.0.0.1`로 제공하고 Claude 데스크톱 앱 내장 Chromium 브라우저에서 `http://127.0.0.1:8761/game/taisei.html`을 열었다.

- 로딩 진행률 표시 후 게임이 시작되어 첫 장면이 렌더링되고 창 제목이 `Taisei Project v1.5-dev`로 바뀌었다.
- 약 25초 동안 리소스 요청 250건 중 `data/` 요청 246건이 모두 `/game/data/` 경로로 나갔고 400 이상 응답은 없었다.
- 게임 로그의 오류 항목은 다음과 같다. 분류는 세션 2의 [RUNTIME.md](RUNTIME.md) 2.1·2.6절 분석을 따른다.
  - `storage/config`, `progress.zst` 없음: 저장 데이터가 없는 첫 실행에서 예상되는 메시지
  - `SDL_CreateSemaphore() failed: SDL not built with thread support`: 웹 빌드는 스레드 비활성이다. 작업 관리자가 없으면 `taskmgr_global_submit()`이 콜백을 즉시 실행하는 동기 폴백으로 동작한다(RUNTIME.md 2.1절).
  - `res/shader/global.pp` 없음 → 후처리 파이프라인 `global` 로드 실패: 선택(`RESF_OPTIONAL`) 후처리 체인이고 기본 리소스에 `.pp` 파일이 없어 화면 영향이 없다(RUNTIME.md 2.6절). Windows 빌드에서도 같은 메시지가 나온다.

키 입력, 스테이지 진입, 오디오, 저장·리플레이는 이 문서의 검증 범위가 아니다. 세션 2·5가 검증한다.

## 제약과 남은 문제

- 게임 리소스 패키지(`data/`) 총 크기는 약 207 MiB다. 리소스는 필요할 때 개별 요청하므로 초기 전송량은 이보다 작으며, 스모크 테스트 25초 동안에는 529개 중 246개를 요청했다. 실제 초기 전송량은 측정하지 않았다. 내려받은 파일은 IDBFS에 캐시된다.
- wasm 바이트 단위 재현성은 확인되지 않았다(머지 차단 조건 아님).
- `SDL_CreateSemaphore` 실패와 `res/shader/global.pp` 누락 메시지의 분류는 [RUNTIME.md](RUNTIME.md)를 따른다. 실제 플레이 영향의 최종 판정은 세션 5의 통합 QA에서 한다.
- 업스트림 셸(`game/taisei.html`) 문구는 영어이며 "실험적(Experimental)" 경고를 표시한다. 한국어 진입 셸은 세션 3의 `web/`(`game/index.html`)이 담당한다.
- macOS·Linux 호스트용 빌드 스크립트는 제공하지 않는다. `configs/web-build/container-build.sh`는 같은 이미지에서 그대로 사용할 수 있다.
