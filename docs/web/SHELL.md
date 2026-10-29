# 웹 셸(web/) — 로딩·시작·게임 화면·오류·조작 안내

담당: 세션 3 · 이슈 [#6](https://github.com/kthss01/mini-danmaku-ai-claude/issues/6) · 부모 [#2](https://github.com/kthss01/mini-danmaku-ai-claude/issues/2)

`web/`는 Taisei WebAssembly 산출물을 감싸는 정적 진입 페이지다. 업스트림 `emscripten/shell.html`을 대체하며, 게임 본체(`taisei.js`/`taisei.wasm`/`data/`)는 수정하지 않는다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `web/index.html` | 서빙 루트 진입 페이지. `game/index.html`로 바로 넘긴다(meta refresh + `location.replace`) |
| `web/game/index.html` | 게임 셸. 상태별 화면(환경 확인·미지원·시작·로딩·플레이·오류·종료), 조작 안내, HUD, 로그 패널 |
| `web/game/shell.css` | 스타일. 상태 전환은 `body[data-state]`와 `section[data-view]`로만 제어 |
| `web/game/shell.js` | 환경 확인, 로더 로딩, Module 콜백, 입력·포커스 정책, 오류 처리 |
| `web/game/shell-config.js` | 게임 산출물과의 연결 지점(파일 이름·팩터리 이름). 계약이 바뀌면 이 파일만 수정 |
| `tests/web-shell/` | mock 로더와 검증용 사이트 구성 스크립트([README](../../tests/web-shell/README.md)) |

세션 1의 패키징 규칙([BUILD.md](BUILD.md), PR #11)대로 `web/`의 파일은 `build/web/site/` 루트로, `web/game/`의 파일은 `build/web/site/game/`으로 복사되어 `taisei.js`·`taisei.wasm`·`data/` 옆에 놓인다. 게임 셸이 `game/`에 있어야 하는 이유는 아래 "산출물 계약"의 `data/` 제약 때문이다. 모든 경로는 페이지 기준 상대 경로이므로 서빙 루트가 어느 하위 경로여도 동작한다. 업스트림 셸 `game/taisei.html`은 그대로 남지만 진입 URL은 `index.html`(→ `game/index.html`)이다.

## 상태 흐름

```
checking ─(미지원)→ unsupported
    └─(지원)→ ready ─[게임 시작 클릭]→ loading ─(onFirstFrame)→ playing ─(onExit)→ exited
                                        │                        │
                                        └──(로더 404·팩터리 거부·abort·예외)→ error ←┘(실행 중 예외)
```

| 상태 | 화면 | 진입 조건 |
| --- | --- | --- |
| `checking` | 스피너 | 페이지 로드 직후 |
| `unsupported` | 원인 목록 + 조작 안내 | WebAssembly/BigInt/IndexedDB/WebGL 2 중 하나라도 없음 |
| `ready` | 시작 버튼 + 조작 안내 + 주의 사항 | 환경 확인 통과 |
| `loading` | 상태 문구 + 진행률 + 경고 | 시작 클릭. 로더 내려받기 → 모듈 준비(`Preparing… (n/m)`) → 저장소 준비 → 리소스 프리페치(`Prefetching resources… (n/m)`) |
| `playing` | canvas 전체 화면 + HUD(조작/전체 화면/로그) | `Module.onFirstFrame()` |
| `error` | 메시지 + 세부 + 다시 시도(새로고침) + 로그 | 아래 "오류 처리" 참조 |
| `exited` | 종료 메시지 + 다시 시작(새로고침) | `Module.onExit(code)` |

게임이 첫 프레임 이후 오류를 내면 게임 화면을 뒤에 남긴 채 오류 패널을 겹쳐 보여준다. 다시 시도는 Emscripten 모듈을 같은 페이지에서 재생성할 수 없으므로 새로고침으로 처리한다.

## 산출물 계약(세션 1 연결 지점)

세션 1의 계약(이슈 #4 댓글, PR #11의 `docs/web/BUILD.md`)과 fork 고정 커밋(5668c41b)의 `src/meson.build`·`emscripten/preamble.js`, 실제 빌드 산출물을 근거로 한다. 파일 이름·팩터리 이름이 바뀌면 `web/game/shell-config.js`만 고친다.

| 항목 | 현재 값 | 근거 |
| --- | --- | --- |
| 로더 | `taisei.js` (`MODULARIZE=1`, `EXPORT_NAME=createTaisei`, `INVOKE_RUN=0`) | `src/meson.build` em_link_args |
| wasm | `taisei.wasm`. 로더가 자기 스크립트 URL 기준으로 찾는다 | Emscripten `locateFile` 기본 동작 |
| 리소스 | `data/<content_id>`를 **HTML 문서 URL 기준 상대 경로**로 fetch | `src/vfs/emscripten_fetch.c`의 `TAISEI_BUILDCONF_DATA_PATH "/%s"` (`data_path = 'data'`) |
| 셸이 넘기는 Module 필드 | `canvas`, `preinitializedWebGLContext`(WebGL 2, 업스트림과 같은 속성), `setStatus`, `onFirstFrame`, `print`, `printErr`, `onAbort`, `onExit` | `emscripten/preamble.js`, `emscripten/postamble.js`, `eventloop/executor_emscripten.c` |
| 셸이 호출하는 인스턴스 메서드 | `await createTaisei(Module)` → `instance.initFilesystem()` → `instance.callMain()` | 업스트림 `shell.html` |
| 기타 정적 파일 | `background.webp`, `favicon.ico`, `COPYING.txt` | 세션 1이 산출물에 포함 |

**`data/` 제약:** 리소스 URL `data/<id>`는 wasm 안의 상수이며 페이지 URL 기준이다(세션 1·2도 같은 결론). 그래서 `createTaisei`를 부르는 셸 페이지는 `data/`와 같은 디렉터리인 `site/game/`에 있어야 하고, 이 저장소에서는 `web/game/`에 둔다. `gameBase`로 로더 위치만 바꿀 수 있고 `data/` 위치는 바꿀 수 없다.

### 상태 문구 해석

`Module.setStatus(text, force)`는 업스트림 셸과 같은 형식 `"문구 (현재/전체)"`를 받아 한국어 문구와 진행률로 바꾼다. 30ms 안의 연속 갱신은 건너뛴다. `playing` 중에 오는 문구(리소스 프리페치)는 HUD 왼쪽에 작게 표시한다.

### 리소스 내려받기 오류 계약(세션 2 fork PR [kthss01/taisei#1](https://github.com/kthss01/taisei/pull/1))

| 런타임 동작 | 셸 처리 |
| --- | --- |
| 내려받기를 포기하면 `Module.setStatus("Error: Failed to download <url> (HTTP status N)", true)` | `Error:`로 시작하는 문구는 상태가 아니라 **내려받기 오류**로 보존(`taiseiShell.downloadErrors`)하고 로딩 화면의 경고 줄과 HUD 경고(빨간 배지)에 표시한다. 이후 상태 갱신이 경고를 덮지 않는다 |
| 필수 리소스면 `log_fatal` → `abort()` → `Module.onAbort` | 오류 패널에 "리소스 내려받기 실패가 원인일 수 있습니다"를 덧붙이고 상세 첫 줄에 마지막 내려받기 오류(URL·HTTP 상태)를 넣는다 |
| 선택 리소스면 로그만 남기고 계속 진행 | 셸은 게임을 멈추지 않는다. 경고 배지만 남는다 |
| 수정 전 빌드(무한 재시도)는 `setStatus`를 보내지 않고 `Module.print`로 `Failed to download …`를 반복 출력 | 첫 문구를 같은 경고로 보여준다(재시도는 런타임이 계속하므로 원인은 서버/산출물에서 해결) |

로더가 `Error:` 접두사를 다른 용도로 쓰지 않는다는 전제이며, Emscripten 자체는 `setStatus`에 그런 문구를 보내지 않는다(업스트림 셸은 `window.onerror`에서만 `Error:`를 만든다).

## 입력·오디오·포커스 정책(세션 2와 분담)

| 항목 | 셸(세션 3) | 런타임(세션 2) |
| --- | --- | --- |
| 오디오 시작 | 시작 버튼 클릭(사용자 제스처) 후에만 모듈을 생성한다. 안내 문구로 "키 입력/클릭 후 재생"을 알린다 | Emscripten `autoResumeAudioContext`가 keydown/mousedown에서 AudioContext를 resume. SDL3 오디오 생성 시점 |
| 키 전달 | 셸은 키를 가로채지 않는다. 단, F11/F12는 `stopImmediatePropagation`으로 게임에 전달하지 않는다(브라우저 전체 화면·개발자 도구 유지, 업스트림과 동일) | SDL3 Emscripten 키보드 핸들러 |
| 스크롤 방지 | `playing` 중 `body { overflow:hidden }` + 방향키·Space·PageUp/Down·Home/End·Tab의 기본 동작 차단(캡처 단계). canvas `touch-action:none` | - |
| 포커스 | canvas `tabindex=0`, 클릭·첫 프레임 시 `focus()`. 창 blur 시 "클릭하면 입력이 다시 전달됩니다" 안내, focus 시 숨김 | 창 blur → SDL `FOCUS_LOST` → 눌린 키 해제. 자동화에서 실제 창 전환을 재현하지 못해 **미검증**(수동 확인 필요) |
| 컨텍스트 메뉴 | canvas에서 차단 | - |
| 화면 크기 | canvas CSS 100vw×100vh. 리사이즈 시 셸이 `canvas.width/height`를 CSS 크기에 맞춘다(업스트림과 동일) | SDL이 DPR을 곱한 드로잉 버퍼 크기로 덮어쓰고 게임이 4:3 레터박스를 그린다(실측: CSS 1024×768 → 1792×1344, DPR 1.75) |
| 전체 화면 | HUD 버튼 → `document.documentElement.requestFullscreen()`. F11도 그대로 브라우저에 전달 | - |
| Esc | 조작 안내 팝업이 열려 있으면 팝업만 닫고 게임에 전달하지 않는다. 그 외에는 게임이 받는다(브라우저 전체 화면 중 Esc는 전체 화면도 해제된다) | 게임 내 일시정지/메뉴 뒤로 |

## 조작 안내 근거

`src/config.h`의 기본 키 바인딩: 이동 방향키, 공격 `Z`, 봄 `X`, 특수 `C`, 저속 `LShift`, 건너뛰기 `LCtrl`, 일시정지 `Pause`/`Esc`(`events.c`), 소리 토글 `M`, 전체 화면 `F11`(웹에서는 브라우저가 처리). 게임 내 Options에서 바꿀 수 있다. 웹 빌드는 `CONFIG_SHOT_INVERTED` 기본값이 1이어서 자동 발사가 기본이고, `Z`를 누르는 동안 발사가 멈춘다(fork PR kthss01/taisei#3).

## 검증

### A. mock 화면 검증(게임 없이)

```powershell
.\tests\web-shell\stage-site.ps1 -Out $env:TEMP\taisei-shell-mock -Mock
python -m http.server 8091 --bind 127.0.0.1 --directory $env:TEMP\taisei-shell-mock
```

`stage-site.ps1`은 세션 1의 패키징과 같은 배치(`web/` → 루트, `web/game/` + 게임 산출물 → `game/`)를 만든다. 브라우저에서 `http://127.0.0.1:8091/index.html`(→ `game/index.html`)을 연다.

2026-10-23, Claude 데스크톱 앱 내장 브라우저(Chromium), 1024×768 및 375×812(모바일 에뮬레이션)에서 확인:

| 항목 | 결과 |
| --- | --- |
| `ready` 화면·조작표·시작 버튼 | 표시됨. 모바일 폭에서 가로 스크롤 없음(scrollWidth 375 = innerWidth) |
| `ok`: 준비 진행률(1/3→3/3) → 첫 프레임 → `playing` → HUD에 프리페치 진행(0/20→20/20) 후 사라짐 | 통과 |
| 방향키·Tab 기본 동작 차단, 일반 키(z)는 차단 안 함, 키가 게임(mock) 리스너에 도달 | 통과(`defaultPrevented=true/true/false`) |
| HUD 조작 안내 열기 → Esc로 닫기(게임에 Esc keydown 미전달), 로그 패널 토글 | 통과 |
| 창 blur/focus 시 안내 표시/숨김 | 통과(합성 이벤트) |
| `reject`, `abort`, `contract`, `nofactory`, 로더 404 → `error` + 원인 메시지 | 통과 |
| `crash` → `error`(게임 화면 유지), `exit` → `exited` | 통과 |
| `download-fail`(수정 전 빌드식 로그) → 경고 문구 표시 | 통과 |
| `asset-fatal`(`setStatus("Error: …")` → abort) → `error`, 상세 첫 줄에 URL·HTTP 404 | 통과 |
| `asset-optional`(첫 프레임 뒤 `setStatus("Error: …")`) → `playing` 유지, HUD 경고 배지가 이후 상태 갱신에 덮이지 않음 | 통과 |
| 로그 패널을 연 채 500줄 초과 → 표시 버퍼도 500줄로 유지 | 통과 |
| `ready`/`error` 상태에서 HUD 숨김 | 통과(초기 구현은 `display:flex`가 `hidden`을 덮어 HUD가 항상 보였음, 수정) |
| WebGL 2 없음 → `unsupported`(getContext를 null로 바꿔 재실행) | 통과 |

`stage-site.ps1`의 원본 삭제 방지 규칙(저장소·`web/`·게임 산출물과 겹치는 출력 거부, marker 없는 기존 디렉터리 거부, 입력 검증을 삭제보다 먼저)은 임시 fixture로 검증한다:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\web-shell\test-stage-site.ps1
```

결과: 23개 검사 모두 통과(`All stage-site safety checks passed`, 종료 코드 0).

### B. 실제 WASM 통합 검증

```powershell
.\tests\web-shell\stage-site.ps1 -Out $env:TEMP\taisei-shell-real -Game build\taisei-web
python -m http.server 8137 --bind 127.0.0.1 --directory $env:TEMP\taisei-shell-real
```

산출물: `scripts/build-web.ps1`(feat/web-playable 작업분, 미머지)로 만든 `build/taisei-web` — fork 커밋 5668c41b41f7227d21fc80cf56997d4d30356ce7, emsdk 5.0.3, `taisei.wasm` 4,538,726 B, `data/` 529개 파일 209 MB. 세션 1 PR #11의 `build/web/site` 자체는 아직 결합하지 않았고, 같은 배치(`game/` 하위)를 `stage-site.ps1`로 재현해 검증했다. 같은 날, 같은 내장 브라우저(Chromium, DPR 1.75)에서 확인:

| 항목 | 결과 |
| --- | --- |
| 루트 `index.html` → `game/index.html` 리다이렉트, `ready` 표시 | 통과 |
| 시작 클릭 → 로더·wasm 내려받기 → `Preparing…` → 리소스 프리페치 진행률(최대 1016) 표시, `data/` 요청이 `/game/data/`로 나감 | 통과 |
| `onFirstFrame` → `playing` 전환, 인트로 컷신 렌더링 | 통과 |
| Z/Ctrl/Esc 입력이 게임에 전달(컷신 진행·건너뛰기) → 메인 메뉴 | 통과 |
| 방향키로 메뉴 이동, Start Story → 난이도 → 캐릭터 → 샷 선택 → Stage 1 진입 | 통과 |
| 스테이지에서 이동(←)·공격(Z) 반영, Esc로 일시정지 메뉴 | 통과 |
| 뷰포트 768×1024로 변경 시 canvas 1344×1792로 갱신, 4:3 레터박스 유지; 복귀 시 1792×1344 | 통과 |
| 셸 오류(`taiseiShell.errors`) | 없음 |
| 새로고침 후 재시작: IndexedDB 캐시 재사용 | 통과. `Loaded persistent storage from IndexedDB`, `data/` 재다운로드 0건, 약 7초 안에 메인 메뉴 도달 |
| 오디오 | 통과. `AudioContext`를 감싸 관찰: 시작 클릭 후 SDL이 만든 컨텍스트가 `running`(48 kHz), 드라이버 `emscripten`. 실제 소리 청취는 내장 브라우저에서 확인하지 못함(세션 5) |
| 전체 화면 버튼 | 내장 브라우저 창에서는 요청이 완료되지 않음. 핸들러 배선은 확인(사용자 제스처 없는 호출은 `Permissions check failed` 로그). **실제 Chrome/Edge에서 수동 확인 필요** |
| 창 전환 시 키 해제 | 자동화로 실제 blur를 만들 수 없어 **미검증** |

#### B-2. 세션 2 수정 빌드로 필수 리소스 누락 검증

세션 2 fork PR #1(head 947edc6b)로 만든 빌드(`taisei.wasm` SHA-256 `0fe02b5d…`, 세션 2 clone의 `build/web-fix`를 복사)를 `stage-site.ps1 -Game`으로 배치한 뒤 `game/data/6e3e30da…`(폰트 `SourceHanSans-Regular-0.ttf`) 1개를 지우고 새 포트(빈 IndexedDB)에서 시작:

| 항목 | 결과 |
| --- | --- |
| 해당 URL 요청 횟수 | 1회(404), 재시도 없음 |
| 로딩 화면 경고 줄 | `리소스 내려받기 실패: Failed to download data/6e3e30da… (HTTP status 404)` |
| 이후 `Required font 'standard_cjk' couldn't be loaded` → abort | `error` 상태, 메시지 "게임 모듈이 비정상 종료되었습니다(abort). 리소스 내려받기 실패가 원인일 수 있습니다.", 상세 첫 줄에 같은 URL·HTTP 404 |

선택 리소스 실패 후 계속 플레이하는 경우는 실제 빌드에서 어떤 리소스가 선택인지 특정하지 못해 mock(`asset-optional`)으로만 확인했다.

게임 쪽 로그에 남은 오류(셸 범위 밖, 담당 세션에 전달):

- `E: VFS error: Node 'res/shader/viewport.pp' does not exist` → 후처리 파이프라인 로드 실패(런타임/빌드, #5·#4)
- `E: rwops_zstd ... SDL_ReadIO() returned 0, expected 9` ×2 (런타임, #5)
- `warning: 2 FS.syncfs operations in flight at once` (IDBFS 동기화 중복, #5)

### C. 공식 산출물 + 세션 4 서버 통합 검증

A·B는 셸을 직접 배치한 사이트로 검증했다. C는 세션 1의 공식 빌드(`build/web/site`)를 그대로 쓰고 세션 4 서버(`scripts/serve-web.py`)로 제공해 확인했다.

산출물 출처(`build/web/site/build-info.json`):

| 항목 | 값 |
| --- | --- |
| Taisei 커밋 | `f59212b72df3b68459b4677a6200e42be700078a` (fork PR #1 머지 커밋 포함 → HTTP 404 같은 영구 오류는 재시도 없이 실패. 0/408/429/5xx는 최대 3회 제한 재시도, 응답이 멈춘 요청은 timeout이 없어 계속 기다림) |
| 빌드한 메인 커밋 | `797f88000b67b88c9f583bbff3e64648fc13d9e7` (PR #15 대상, 미커밋 변경 없음) |
| 빌드 시각(UTC) | 2026-10-23 12:31:22 ~ 12:35:37 |
| `site.entry` | `game/index.html` |
| `game/taisei.wasm` | 4,539,198 B, SHA-256 `76f6b39da5aa417fd41c7cbfb59da4216df0e7a3f1f02feb3c8be97fd1826192` |
| `data/` | 529개, 217,186,447 B |
| 셸 파일 | `index.html`, `game/index.html`, `game/shell.js`가 main(`03f580b`)의 `web/`와 동일 |

세션 1 clone의 `build/web/site`를 이 clone의 Git 제외 경로 두 곳에 복사했다. 하나는 그대로 두고, 다른 하나는 `game/data/6e3e30da…`(폰트) 1개를 지웠다.

```powershell
python scripts/serve-web.py --root build/web-official --port 8141 --quiet
python scripts/serve-web.py --root build/web-official-missing --port 8142 --quiet
```

서버 응답(두 포트 공통): `/`, `/game/index.html` → 200 `text/html`. `/game/taisei.wasm` → 200 `application/wasm`. `/game/shell.js` → 200 `text/javascript`. 모두 `Cache-Control: no-store`. 지운 폰트는 8142에서만 404였다.

2026-10-23, Claude 데스크톱 앱 내장 브라우저(Chromium, 1024×768, DPR 1.75), 새 포트라 빈 IndexedDB에서 확인:

| 항목 | 결과 |
| --- | --- |
| `/` → `game/index.html` 리다이렉트, `ready`, HUD 숨김 | 통과 |
| 시작 → 프리페치 진행률(/1016) → 첫 프레임 → `playing` | 통과 |
| 왼쪽 Ctrl 유지로 인트로 컷신 건너뛰기 → 메인 메뉴 | 통과 |
| Z로 Start Story → 난이도 → 캐릭터 → 샷 → Stage 1 진입, ←·Z 반영, Esc 일시정지 메뉴 | 통과 |
| canvas 포커스 유지, `scrollY` 0, 셸 오류·내려받기 오류 0건 | 통과 |
| 오디오 | SDL이 만든 `AudioContext`가 `running`. 실제 소리 청취는 미확인 |
| 새로고침 후 재시작 | `Loaded persistent storage from IndexedDB`, `data/` 재다운로드 0건, 8초 안에 `playing` |
| 폰트 누락(8142) | 해당 URL 요청 1회(404) → `Required font 'standard_cjk'` → abort. 셸은 `error`, 상세 첫 줄에 `Failed to download data/6e3e30da… (HTTP status 404)` 표시. 같은 리소스의 로그 문구와 `setStatus` 문구는 1건으로 합쳐짐 |

게임 로그의 런타임 오류는 B와 같다(`viewport.pp` 없음, `rwops_zstd` seektable ×2, `FS.syncfs` 중복 경고). 세션 2가 `docs/web/RUNTIME.md`에서 분류했다.

**수정 전후 구분(필수 리소스 HTTP 404 시나리오에 한정):** B의 원본 빌드(fork `5668c41b`)는 리소스가 없으면 무한 재시도하므로 셸은 경고만 띄우고 로딩이 멈춘다. C의 공식 빌드(fork `f59212b7`)는 404 응답에 대해 1회 요청 후 실패로 끝나고 셸이 원인을 오류 패널에 보여준다. 503 등 일시적 오류는 제한 재시도 경로이고, 응답이 멈춘 요청은 timeout이 없어 기다리므로 이 결과를 일반화하지 않는다(둘 다 이 검증에서 재현하지 않음).

### 검증하지 않은 것

- Chrome/Edge 실제 브라우저 창에서의 전체 화면, 실제 창 전환 시 키 해제, 5분 이상 플레이·FPS·사운드 청취(세션 5 QA 범위)
- 실제 빌드에서 선택 리소스 실패 후 계속 플레이(mock `asset-optional`로만 확인)
- PR #15 머지 후 main의 깨끗한 checkout에서 다시 만든 산출물. C는 PR #15 대상 커밋 `797f880`으로 세션 1이 만든 산출물을 썼다

## 범위 제외

폰 터치 조작, 새 게임 엔진, AI, UI 프레임워크 도입.
