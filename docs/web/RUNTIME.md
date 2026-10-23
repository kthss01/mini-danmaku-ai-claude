# Taisei 웹 런타임 호환성·입력·저장 (세션 2 / 이슈 #5)

담당 이슈: [#5](https://github.com/kthss01/mini-danmaku-ai-claude/issues/5) · 부모: [#2](https://github.com/kthss01/mini-danmaku-ai-claude/issues/2)
조사 기준 소스: fork `kthss01/taisei` 고정 커밋 `5668c41b41f7227d21fc80cf56997d4d30356ce7` (upstream `master`와 동일), fork SDL3 `taisei-3.4.12`
조사일: 2026-10-23

이 문서는 Taisei 소스가 브라우저(Emscripten/WebAssembly)에서 어떻게 동작하는지, 세션 1(빌드)·3(셸)·4(서버)·5(QA)가 지켜야 할 런타임 요구사항, 그리고 소스 수정이 필요했던 지점과 그 근거를 정리한다. 빌드 명령과 산출물 배치는 세션 1 문서, 셸 UI는 세션 3 문서, 서버는 세션 4 문서가 담당한다.

## 1. 결론 요약

| 항목 | 결과 |
| --- | --- |
| 소스의 웹 지원 범위 | 고정 커밋에 Emscripten 전용 VFS(`src/vfs/*emscripten*`), 메인 루프(`src/eventloop/executor_emscripten.c`), 셸 연동 JS(`emscripten/preamble.js`, `postamble.js`, `shell.html`)가 이미 포함 |
| 수정 없이 동작 확인 | 시작 → 인트로 컷신 → 메인 메뉴 → 난이도·캐릭터 선택 → 스테이지 1 플레이(이동·공격·피격·컨티뉴·포기) → 리플레이 저장 → 새로고침 후 설정·진행도·리플레이 재조회 및 재생 |
| 소스 차원의 플레이 차단 원인 | 이번에 관찰한 범위(내장 Chromium, 로컬 HTTP, 스테이지 1까지)에서는 없음. 단, `data/` 파일 누락·불일치 시 **무한 재시도로 로딩이 멈추는** 문제를 재현했고 fork에서 수정(4절) |
| 스레드·헤더 | pthreads 미사용 → COOP/COEP 불필요 |
| 저장소 | IndexedDB(IDBFS) `/persistent`. 설정·진행도·리플레이·리소스 캐시 모두 여기에 저장 |
| 오디오 | SDL3 emscripten 드라이버가 첫 사용자 입력 후 자동 재개. 셸 JS 불필요 |
| 미검증 | 실제 Chrome/Edge에서의 탭 전환(blur) 시 키 해제·일시정지, 스피커 출력, 게임패드. 세션 5가 수행 |

검증 환경: Claude Code 내장 브라우저(Chromium, ANGLE D3D11 / AMD Radeon 780M), Windows 11, 로컬 HTTP `127.0.0.1:8092`, 메인 clone에 남아 있던 기존 웹 빌드(emsdk 5.0.3, 2026-10-23 20:18 생성)를 별도 clone의 `build/web-test/`로 복사해 사용.

## 2. 런타임 구조

### 2.1 스레드 · 메모리 · 브라우저 요구사항

| 항목 | 값 | 근거 |
| --- | --- | --- |
| pthreads | 사용 안 함 | `misc/ci/emscripten-build.ini`의 `[sdl3-cmake-wrapper:project options] pthreads = 'disabled'`, `src/meson.build`의 링크 옵션에 `-pthread` 없음 |
| 작업 관리자 | 동기 폴백 | 실행 로그 `taskmgr_create: SDL_CreateSemaphore() failed: SDL not built with thread support` → `taskmgr_global_submit()`이 `g_taskmgr == NULL`이면 콜백을 즉시 실행(`src/taskmanager.c`). 리소스 비동기 로딩은 `postamble.js`의 `ENV.TAISEI_NOASYNC=1`로 끔 |
| COOP/COEP | 불필요 | `typeof SharedArrayBuffer === 'undefined'`, `crossOriginIsolated === false` 상태에서 정상 실행 |
| WASM 메모리 | `INITIAL_MEMORY=256MiB`, `ALLOW_MEMORY_GROWTH=1`, `STACK_SIZE=1MB` | `src/meson.build` `em_link_args` |
| 코루틴 | Asyncify | `emscripten_sleep()`을 쓰는 fetch 대기(`emscripten_fetch.c`)와 koishi 코루틴이 Asyncify에 의존. `ASYNCIFY_REMOVE` 목록으로 코드 크기 억제 |
| 브라우저 최소 | Chrome 91 / Firefox 89 | `-sMIN_CHROME_VERSION=91 -sMIN_FIREFOX_VERSION=89`, WASM SIMD128·bulk-memory·sign-ext·BigInt 사용 |
| 환경 변수 | `TAISEI_NOASYNC=1`, `TAISEI_NOUNLOAD=1`, `TAISEI_PREFER_SDL_VIDEODRIVERS=emscripten`, `TAISEI_RENDERER=gles30` | `emscripten/postamble.js`가 `ENV`에 고정. 셸에서 바꿀 필요 없음 |
| 종료 | 없음 | `EXIT_RUNTIME=0`, `taisei_is_quit_hidden()`이 웹에서 항상 true → 메뉴에 Quit 항목 없음 |

### 2.2 WebGL · 캔버스

- WebGL 2 필수: `-sMIN_WEBGL_VERSION=2 -sMAX_WEBGL_VERSION=2`. 렌더러는 `gles30`(gl33은 `src/renderer/meson.build`에서 emscripten 제외), 셰이더는 빌드 시 오프라인 변환.
- 컨텍스트는 **셸이 먼저 생성**해 `Module.preinitializedWebGLContext`로 전달한다(`-sGL_PREINITIALIZED_CONTEXT=1`). 업스트림 셸(`emscripten/shell.html`)의 속성:

```js
canvas.getContext('webgl2', {
    alpha: false, antialias: false, depth: false, stencil: false,
    premultipliedAlpha: true, preserveDrawingBuffer: false,
    powerPreference: 'high-performance',
});
```

- `preamble.js`가 `getSupportedExtensions()` 전부를 `getExtension()`으로 활성화한다(Emscripten이 미활성 확장도 `GL_EXTENSIONS`에 보고하는 비호환 동작 보정). 셸이 중복 처리할 필요 없음.
- 캔버스 선택자는 SDL 기본 `#canvas`, 키보드 이벤트 대상은 `#window`(`SDL_HINT_EMSCRIPTEN_CANVAS_SELECTOR`, `SDL_HINT_EMSCRIPTEN_KEYBOARD_ELEMENT` 기본값, `SDL_emscriptenvideo.c`). 셸 캔버스의 `id`는 `canvas`여야 한다.
- 전체화면·해상도 변경·적응형 vsync는 웹에서 `VIDEO_NEVER_AVAILABLE`(`video_query_capability_webcanvas`, `src/video.c`). 시작 시 `fullscreen=0`을 강제한다. 캔버스 크기는 CSS 크기를 따르며 업스트림 셸은 `window.onresize`에서 `canvas.width/height = offsetWidth/offsetHeight`로 맞춘다.
- 메인 루프는 `emscripten_set_main_loop(cb, 0, false)`(requestAnimationFrame 기반, `executor_emscripten.c`). 비디오 모드 변경 이벤트마다 루프를 재등록하고 vsync 설정을 다시 적용한다. 첫 프레임에서 `Module.onFirstFrame()`을 호출한다.
- 실행 로그: `OpenGL ES 3.0 (WebGL 2.0 (OpenGL ES 3.0 Chromium))`, `Renderer backend gles30 initialized`. `texture_norm16`, `texture_rg`, ETC/PVRTC/ASTC 등 "Extension not supported" 경고는 치명적이지 않다.

### 2.3 파일시스템 · 저장

로더 계약(세션 1 댓글과 동일, `emscripten/shell.html`):

```js
const taisei = { canvas, preinitializedWebGLContext: gl, onFirstFrame, print, printErr, setStatus };
await createTaisei(taisei);   // MODULARIZE, EXPORT_NAME=createTaisei, INVOKE_RUN=0
taisei.initFilesystem();       // preamble.js: FS.mkdir('/persistent'); FS.mount(IDBFS, {}, '/persistent')
taisei.callMain();
```

- `initFilesystem()`은 **반드시 `callMain()` 전에** 호출한다. `vfs_setup()`(`src/vfs/setup_emscripten.c`, `VFS_SETUP_SYNCING`)이 시작 직후 `FS.syncfs(true)`로 IndexedDB를 읽고, 완료 콜백 `vfs_sync_callback`에서 `/persistent/storage`, `/persistent/cache`를 마운트한 뒤 초기화를 계속한다. `preamble.js`의 `SyncFS()`가 이 콜백을 `ccall(..., {async: true})`로 호출한다.
- IndexedDB: DB 이름 `/persistent`, 오브젝트 스토어 `FILE_DATA`(IDBFS 표준). 주요 경로:

| 경로 | 내용 | 기록 주체 |
| --- | --- | --- |
| `/persistent/storage/config` | 설정 파일(`config_save`, 임시 파일 `config~` → rename) | `src/config.c` |
| `/persistent/storage/progress.zst` | 진행도·하이스코어·해금 | `src/progress.c` |
| `/persistent/storage/replays/*.tsr` | 리플레이 | `src/replay/replay.c` |
| `/persistent/storage/screenshots/` | P 키 스크린샷(브라우저 다운로드 아님) | `src/video.c` |
| `/persistent/storage/log.txt` | 파일 로그(웹 기본 레벨 `LOG_NONE`이라 사실상 비어 있음) | `src/log.c` |
| `/persistent/cache/textures/...` | 변환된 압축 텍스처 캐시 | 텍스처 로더 |
| `/persistent/res-cache/<sha256>` | **다운로드한 `data/` 파일 전체(약 209 MB)** | `src/vfs/emscripten_fetch.c` |

- IndexedDB 동기화(`FS.syncfs(false)`) 시점. 전부 소스가 담당하므로 셸 JS가 저장 코드를 추가할 필요가 없다.
  - 메뉴/스테이지 루프 진입: `eventloop_enter()` (`src/eventloop/eventloop.c`)
  - 옵션 메뉴 종료, 게임 시작 직전, 스테이지 종료, 첫 메인 메뉴: `taisei_commit_persistent_data()` → `config_save()` + `progress_save()` + sync (`src/global.c`; 호출 지점 `menu/submenus.c`, `menu/common.c`, `stage.c`, `main.c`)
  - 리플레이 저장 직후: `replay_save()`
  - VFS 종료: `vfs_shutdown()`
  - `beforeunload`에서는 추가 저장이 없다. 마지막 커밋 이후 변경(예: 옵션 메뉴를 나가지 않고 새로고침)은 유실될 수 있다.
- 리소스 로딩: 리소스 인덱스는 wasm에 정적으로 내장되고(`use_static_res_index`), 파일은 `"data/" + content_id`를 `emscripten_fetch`로 요청한다(`TAISEI_BUILDCONF_DATA_PATH = 'data'`, relocatable install). 이 URL은 **게임을 실행하는 HTML 문서 기준 상대 경로**다(`locateFile`은 `taisei.wasm`에만 적용). 첫 실행은 동시 4개씩 전체 파일을 미리 받아 `res-cache`에 저장하고, 두 번째 실행부터 네트워크 요청은 0건이었다.
- 저장 데이터는 **오리진(스킴+호스트+포트)별**로 분리된다. 서빙 포트가 바뀌면 빈 저장소에서 시작하고 209 MB를 다시 받는다.
- 릴리스 빌드는 `--closure 1`이라 `Module.FS`의 메서드명이 난독화된다. 셸이나 QA 스크립트에서 `FS.readdir` 등을 직접 호출할 수 없고, 저장 내용은 표준 `indexedDB.open('/persistent')`로 조회해야 한다.

### 2.4 입력 · 포커스

- 키 이벤트는 SDL3 emscripten 백엔드가 `window`에 등록한다(`SDL_emscriptenevents.c: Emscripten_RegisterEventHandlers`). 방향키·Tab·Backspace·F1~F12·Ctrl 조합은 `preventDefault`되어 **페이지 스크롤이 일어나지 않는다**(`Emscripten_HandleKey`). 업스트림 셸은 F11/F12의 `stopImmediatePropagation`만 추가한다.
- 포커스 해제: `window` `blur` 시 SDL이 `SDL_ResetKeyboard()`로 눌린 키를 전부 해제하고 `SDL_EVENT_WINDOW_FOCUS_LOST`를 보낸다(`Emscripten_HandleFocus`). Taisei는 `focus_loss_pause = 1`(기본)이면 `TE_GAME_PAUSE`를 발생시켜 스테이지를 일시정지한다(`src/video.c`). 창 생성 시 `SDL_SetKeyboardFocus(window)`가 호출되므로(`SDL_emscriptenvideo.c`) 첫 blur부터 적용된다.
- **내장 브라우저의 탭 전환은 `window` `blur`를 발생시키지 않아 이 경로를 실측하지 못했다.** 합성 `blur` 이벤트로는 의미 있는 검증이 되지 않아 생략했다. Chrome/Edge에서 다른 창으로 전환했을 때 (1) 눌린 이동 키가 풀리는지, (2) 일시정지 메뉴가 뜨는지가 세션 5의 QA 항목이다.
- 기본 키(`src/config.h`): 이동 방향키, Z 공격·메뉴 선택, X 봄·메뉴 취소, C 파워 서지, Shift 저속, Esc 일시정지, **왼쪽 Ctrl 컷신 스킵**, F1 즉시 포기, F2 재시작, P 스크린샷, M 음소거.
- 실측: 메인 메뉴 이동·선택, 난이도·캐릭터 선택, 스테이지 1 진입, 이동·공격·피격·컨티뉴·포기, 리플레이 저장 프롬프트가 모두 키보드로 동작했다. 스테이지 중 화면 우하단 FPS 표시 약 61 fps.
- 게임패드: `res/gamecontrollerdb.txt`가 웹 정적 리소스 인덱스에 포함되지 않아 `Couldn't load mappings` 경고가 나온다(`resources/meson.build`가 emscripten에서 `subdir_done()`). 키보드 플레이에는 영향 없음. 게임패드 지원은 이번 범위 밖.

### 2.5 오디오

- SDL3 emscripten 오디오 드라이버(`Available audio drivers: emscripten disk dummy`, `Using driver 'emscripten'`), `ScriptProcessorNode` 기반(`SDL_emscriptenaudio.c`). 자동재생이 차단되면 SDL이 `navigator.userActivation.hasBeenActive`를 폴링해 `AudioContext.resume()`을 호출하고, 그때까지는 무음 버퍼로 게임 로직을 계속 돌린다. Taisei의 `-sDEFAULT_LIBRARY_FUNCS_TO_INCLUDE=$autoResumeAudioContext`는 `userActivation`이 없는 구형 브라우저용 보조(keydown/mousedown/touchstart 1회 리스너).
- 실측: 로드 직후 `userActivation.hasBeenActive === false`, 캔버스 클릭 1회 후 `AudioContext.state === 'running'`(48 kHz). **셸은 "클릭 또는 키 입력 후 소리가 난다"는 안내만 하면 되고 별도 resume 코드는 불필요하다.** 실제 스피커 출력은 세션 5가 확인한다.

### 2.6 로그 · 디버깅

- 게임 로그는 `Module.print`로 전달되어 콘솔과 업스트림 셸의 `#output` textarea("Show log")에 모두 쌓인다. 첫 실행은 fetch 로그가 1000줄을 넘어 DevTools 콘솔 버퍼가 밀릴 수 있으므로 textarea 쪽이 안정적이다. 웹 콘솔 기본 레벨은 `LOG_ALERT | LOG_INFO`(`src/log.h`).
- 치명 오류(`log_fatal`)는 `abort()` → `RuntimeError: Aborted()`로 `window.onerror`에 도달하고 업스트림 셸이 `Error: ...`로 표시한다. `ASSERTIONS=0`이라 메시지에 원인은 없고, 원인은 그 직전 `E:` 로그를 봐야 한다.
- 정상 실행에서도 나오는 오류·경고. 아래 분류는 소스 근거와 이번 관찰 범위에 한정한 판단이며, 다른 증상이 함께 나타나면 다시 봐야 한다.
  - `rwzstd_reader_init_seektable ... SDL_ReadIO() returned 0, expected 9`: `rwzstd_open_reader()`가 seekable 포맷의 seek table을 "있으면" 읽는 시도이며, 없으면 프레임 헤더로 폴백한다(`src/rwops/rwops_zstd.c`). `/persistent/cache/textures/` 캐시 파일에서 발생. 텍스처는 정상 표시됨.
  - `Node 'res/shader/global.pp' does not exist`, `viewport.pp` 관련 오류: 둘 다 `RESF_OPTIONAL`로 로드하는 사용자 정의 후처리 체인이다(`src/video_postprocess.c`의 `"global"`, `src/stagedraw.c`의 `"viewport"`). 기본 리소스에는 `.pp` 파일이 없고(`resources/` 트리에 `*.pp` 없음), `postprocess()`는 체인이 비어 있으면 그대로 반환하므로 화면 영향이 없다. `kvparser`가 VFS 오류를 `E:`로 찍을 뿐이다.
  - `Node 'res/config.default' does not exist`: 선택 파일(`config_load_file`, `LOG_INFO`), 첫 실행의 `storage/progress.zst ... No such file`: 첫 실행 전용
  - `Couldn't load mappings: res/gamecontrollerdb.txt`(2.4절)

## 3. 세션별 요구사항 정리

| 세션 | 요구사항 |
| --- | --- |
| 1 (빌드) | 산출물 계약(`site/game/` 아래 `taisei.html`·`taisei.js`·`taisei.wasm`·`data/`)에 동의. 추가 소스 수정 요구 없음. fork 수정 커밋(4절)을 gitlink에 반영 |
| 3 (셸) | 업스트림 셸을 유지하거나, 교체 시 `Module`의 `canvas`·`preinitializedWebGLContext`·`onFirstFrame`·`setStatus`·`print`·`printErr` 계약과 `createTaisei → initFilesystem → callMain` 순서를 지킬 것. 캔버스 `id="canvas"`. 입력 preventDefault·오디오 resume·저장 JS는 중복 작성 불필요. 게임 페이지는 `game/` 아래(`game/index.html` 또는 `game/taisei.html`)에서 실행하는 것으로 확정하며, 루트에서 `createTaisei`를 직접 호출하기 위한 데이터 URL 접두사 소스 수정은 범위에서 제외. 다운로드 실패 시 `Module.setStatus("Error: Failed to download …")` 뒤에 필수 리소스면 `abort()`가 이어지므로, 셸의 `onerror`/`onAbort`는 `Module.lastDownloadError`(4.2절)가 있으면 그 원인을 함께 표시할 것 |
| 4 (서버) | `.wasm` → `application/wasm`, 확장자 없는 `data/*`는 아무 MIME이나 가능(로더가 `application/octet-stream`으로 덮어씀), COOP/COEP 불필요, `Cache-Control: no-store` 가능(게임이 IndexedDB에 자체 캐시) |
| 5 (QA) | Chrome/Edge에서 탭 전환(blur) 시 키 해제·일시정지, 스피커 출력, 아래 4·5절의 검증 절차 수행 |

## 4. 소스 수정: 리소스 다운로드 실패 시 무한 재시도 중단

### 4.1 문제

`src/vfs/emscripten_fetch.c`의 `vfs_fetch_open()`은 HTTP 200이 아니면 조건 없이 같은 URL을 다시 요청했다.

```c
for(;;) {
    fetch = fetch_begin_request(ctx, content_id);
    fetch_wait(fetch);          // emscripten_sleep(10) 폴링
    if(fetch->status == 200) break;
    emscripten_fetch_close(fetch);
}
```

재현(테스트 디렉터리에서 시작 시 필요한 폰트 파일 `data/6e3e30da…` 1개를 제거하고 IndexedDB를 비운 뒤 로드):
- 10초 동안 같은 URL에 404 요청 620회 이상(네트워크 패널 1000건 이상 버퍼 초과)
- 셸 상태 표시는 빈 문자열, 게임 화면 없음 → 사용자는 원인을 알 수 없고 새로고침해도 반복
- `data/` 파일 누락, 빌드와 산출물 불일치(인덱스는 wasm에 내장), 서버 경로 오류 모두 같은 증상

### 4.2 수정

fork PR [kthss01/taisei#1](https://github.com/kthss01/taisei/pull/1), 브랜치 `feat/web-fetch-fail-fast`, 커밋 `947edc6b`(재시도 제한) + `69a2ab97`(오류 원인 보존), head `69a2ab9733c69858617ace90c9b6e058e71726f9`. 머지 후 세션 1이 메인 `game/taisei` gitlink를 머지 커밋으로 갱신한다.

- 네트워크 단절(status 0)·408·429·5xx 같은 일시적 오류만 **횟수 기준** 최대 3회 시도(실패 후 0.5 s, 1 s 대기) 후 포기. 이것은 총 소요 시간 제한이 아니다. `emscripten_fetch_attr_t.timeoutMSecs`를 설정하지 않으므로(0 → Emscripten `Fetch.js`에서 timeout 미적용) 응답이 끝나지 않고 멈춘 연결은 `fetch_wait()`가 계속 기다린다. 서버가 응답을 끊거나 오류 코드를 돌려주는 경우만 이 수정의 대상이다.
- 404 등 그 외 응답은 첫 실패에서 바로 `vfs_set_error()`로 실패를 반환한다.
- 포기 시점에 `Module.setStatus("Error: Failed to download <url> (HTTP status N)", true)`로 셸에 표시하고, 같은 문자열을 `Module.lastDownloadError`에 남긴다. 이 표시는 필수·선택 리소스 구분 없이 일어난다.
- 그다음은 Taisei의 기존 리소스 로더가 처리한다. 필수 리소스(`RESF_DEFAULT`)면 `Required ... couldn't be loaded` → `log_fatal` → `abort()`로 중단되고, 선택 리소스(`RESF_OPTIONAL`)면 `Failed to load ...` 오류 로그만 남기고 게임은 계속 진행한다(상태 표시줄의 오류 문구는 남는다).
- 백그라운드 prefetch(`prefetch_next`)의 실패는 `fetch_onerror` 로그만 남기고 재시도하지 않는다. 재시도는 실제로 그 파일을 여는 `vfs_fetch_open()`에서만 일어난다.

### 4.3 검증

빌드: 공식 CI와 같은 Docker 이미지 `taiseiproject/linux-toolkit:20260804`, emsdk 5.0.3, cross-file `common-options` / `forcefallback` / `emscripten-build`, `-Dbuild.cpp_std=gnu++14`. 두 커밋 모두 `meson compile`/`install` 성공(각 약 5분).

| head | `taisei.wasm` SHA-256 | 비고 |
| --- | --- | --- |
| `947edc6b` | `0fe02b5d82865b9b0f9e93e92b1edbeff2979dbf9fe3965cc6b342e4103182b6` | 재시도 제한 |
| `69a2ab97` | `c8fec8c8f5d5ce6d690f85be7557b3f9f663638dbda19412c5ae416f08a9b330` | + `lastDownloadError` |

실행: Claude Code 내장 Chromium. 시나리오마다 다른 포트(= 다른 오리진)를 써서 IndexedDB가 비어 있는 상태에서 시작했고, 대상 리소스는 시작 직후 필수 폰트로 열리는 `data/6e3e30da…`(SourceHanSans-Regular-0.ttf, 리소스 인덱스 #32)이다. 결함 주입 서버는 지정 경로에 대해 처음 N회 503을 돌려주고 모든 요청을 타임스탬프와 함께 기록한다.

| 시나리오 | head | 대상 URL 요청(서버 로그) | 게임 로그 | 결과 |
| --- | --- | --- | --- | --- |
| 정상 데이터 | 둘 다 | 각 파일 1회 | `Initialization complete` | 인트로 컷신 렌더링. 동작 변화 없음 |
| 404(파일 제거) | `947edc6b` | **1회** | `Giving up … after 1 attempt(s); last HTTP status 404` → `Required font 'standard_cjk' couldn't be loaded` → `Aborted()` | 셸 상태 `Error: Failed to download data/6e3e30da… (HTTP status 404)`. 수정 전 같은 조건: 10초 동안 620회 이상, 표시 없음 |
| 503 → 503 → 200 | `69a2ab97` | 3회: +0.000 s 503(prefetch), +0.125 s 503(open 1차), +0.532 s 200(open 2차) | `Retrying … (attempt 2 of 3)` → `fetch_onsuccess: Cached …` → `Initialization complete` | 게임 정상 시작, 상태 표시 없음 |
| 항상 503 | `69a2ab97` | **4회**: +0.000 s(prefetch), +0.125 s(open 1차), +0.531 s(open 2차), +1.578 s(open 3차) | `Retrying (attempt 2 of 3)` → `Retrying (attempt 3 of 3)` → `Giving up … after 3 attempt(s); last HTTP status 503` → 필수 폰트 fatal → `Aborted()` | 셸 상태 `Error: … (HTTP status 503)`, `Module.lastDownloadError`에 같은 문자열 보존 |

- 재시도 간격은 코드의 0.5 s·1 s 대기와 `fetch_wait()`의 10 ms 폴링이 합쳐진 값이다(서버 로그 기준 약 0.41 s, 1.05 s).
- 백그라운드 prefetch 요청(1회, 재시도 없음)과 `vfs_fetch_open()` 재시도(최대 3회)는 게임 로그에서 `Retrying` 줄 유무로 구분된다. 같은 페이지 로드에서 총 요청은 prefetch 1 + open 최대 3 = 4회를 넘지 않았다.
- 503 소진 시나리오를 두 번 실행했고 두 번째 실행(8097)에서 위 수치를 얻었다. 첫 번째 실행(8095)의 서버 로그에는 같은 4회 묶음이 두 번 기록됐는데, 서버가 뜨기 전 실패한 탐색을 브라우저가 재시도해 페이지가 두 번 로드된 것으로 설명된다(묶음 사이 약 6 s, 각 묶음 내부 간격은 동일).
- 미검증: status 0(네트워크 단절)·408·429 분기는 503과 같은 코드 경로(`fetch_status_is_transient`)라 별도 실행하지 않았다. 응답이 멈춘 연결(stall)은 timeout이 없어 계속 기다리며(4.2절), 재현하지 않았다.
- 참고: 로컬 clone으로 빌드하면 버전 문자열이 태그 유무에 따라 달라진다(`v1.5-dev` 대 `v1.4-831-g69a2ab97`). 동작과 무관하며 세션 1의 빌드 스크립트가 태그를 포함해 clone하는지 확인하면 된다.

## 5. 저장(persistence) 검증 절차

세션 5가 Chrome/Edge에서 수행할 절차. 모두 같은 오리진(같은 호스트·포트)에서 진행한다.

1. 첫 로드 후 캔버스를 클릭하고 Ctrl을 눌러 인트로 컷신을 건너뛴다. 메인 메뉴가 나오면 로그에 `Saved config to /persistent/storage/config`, `Saved progress to /persistent/storage/progress.zst`, `Saved persistent storage to IndexedDB`가 있어야 한다.
2. Options에서 설정 하나(예: SFX 볼륨)를 바꾸고 메뉴를 나간다(이때 `taisei_commit_persistent_data`).
3. Start Story → 난이도 → 캐릭터 → 스테이지 1에서 잠시 플레이 → F1(즉시 포기) 또는 게임 오버 → "Save Replay?"에서 Yes. 로그에 `Saving /persistent/storage/replays/taisei_<일시>_stg1_<캐릭터>_<난이도>.tsr`가 남는다.
4. 새로고침. 기대 결과: 인트로 컷신이 다시 나오지 않음, `Loading configuration from /persistent/storage/config`, 바꾼 설정 유지, 하이스코어 유지, Replays 메뉴에 3번 리플레이가 표시되고 재생됨. 두 번째 로드부터 `data/` 네트워크 요청은 0건.
5. DevTools → Application → IndexedDB → `/persistent` → `FILE_DATA`에서 `/persistent/storage/config`, `progress.zst`, `replays/*.tsr` 키를 확인한다. 스크립트로는 다음과 같이 조회할 수 있다.

```js
const db = await new Promise((ok, no) => { const r = indexedDB.open('/persistent'); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
const keys = await new Promise(ok => { const k = db.transaction('FILE_DATA').objectStore('FILE_DATA').getAllKeys(); k.onsuccess = () => ok(k.result); });
keys.filter(k => k.startsWith('/persistent/storage'));
```

제약: 브라우저 저장소를 지우거나 시크릿 창을 닫으면 모두 사라진다. 리플레이는 브라우저 밖으로 내보내는 기능이 없다(필요하면 후속 이슈).

## 6. 남은 문제·미검증

- 실제 Chrome/Edge에서의 blur 시 키 해제·일시정지, 스피커 출력, 5분 이상 플레이 안정성, FPS 측정 → 세션 5
- 게임패드 매핑 파일 미포함(2.4절). 키보드 플레이 범위에서는 문제 없음
- 리플레이·스크린샷을 파일로 내보내기 → 범위 밖, 필요 시 후속 이슈
- 응답이 끝나지 않는 연결(stall)에 대한 fetch timeout은 설정하지 않음(4.2절). 필요해지면 `timeoutMSecs` 도입을 별도 fork PR로 검토
- 루트 페이지에서 `createTaisei`를 직접 호출하기 위한 데이터 URL 접두사 수정은 `game/` 배치 확정에 따라 범위에서 제외
