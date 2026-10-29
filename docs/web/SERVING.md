# 웹 산출물 로컬 HTTP 제공과 리소스 검사

담당: 세션 4 ([이슈 #7](https://github.com/kthss01/mini-danmaku-ai-claude/issues/7)), 부모 [#2](https://github.com/kthss01/mini-danmaku-ai-claude/issues/2)
검증일: 2026-10-23 (공식 산출물 재검증 포함)

Taisei 웹 빌드(HTML/JS/WASM/리소스)를 로컬에서 제공하는 명령과, 산출물의 파일 참조·경로·MIME·HTTP 헤더를 검사하는 도구를 정리한다. 공개 배포는 범위에 포함하지 않는다. 로컬 URL(`http://127.0.0.1:…`)은 공개 URL이 아니다.

## 요약

| 항목 | 결과 |
| --- | --- |
| 서버 명령 | `python scripts/serve-web.py` (기본 루트 `build/web/site`, `127.0.0.1:8080`) |
| 검사 명령 | `python scripts/check-web-assets.py --root <산출물> [--entry …] [--url http://127.0.0.1:8080] [--require-wasm]` |
| WASM MIME | `application/wasm` 제공·검사 확인 |
| 스레드(pthreads) | 현재 빌드는 사용하지 않음 → COOP/COEP 격리 헤더 불필요(옵션으로 제공) |
| 리소스 경로 | `data/<sha256>` 상대 경로, 529개 207.1 MiB, 내용 해시 전부 일치 |
| fixture 테스트 | 55개: Windows 54 통과 + symlink 권한 없어 1 skip, Linux(Docker python:3.12) 54 통과 + Windows 전용 1 skip (`tests/web-server`) |
| 공식 산출물 검사 | main `fd9e00e`(Taisei `f59212b7`)의 `build/web/site`: 진입 3종(`index.html`, `game/index.html`, `game/taisei.html`) 모두 통과. 직전 main `03f580b` 산출물도 같은 결과, 브라우저에서 루트 진입→시작→인트로 장면까지 리소스 실패 0 |
| 탐색 검증(이전) | 기존 로컬 빌드 평면·중첩 배치 통과(HTTP 541건) |

## 전제: 산출물 구조

세션 1([#4](https://github.com/kthss01/mini-danmaku-ai-claude/issues/4), PR #11)과 세션 3([#6](https://github.com/kthss01/mini-danmaku-ai-claude/issues/6), PR #12)이 머지한 계약이다. 자세한 패키징 규칙은 `docs/web/BUILD.md`, 셸 구조는 `docs/web/SHELL.md`가 기준이다.

```text
build/web/site/            ← 서빙 루트 (--root 기본값)
  index.html               ← 세션 3 루트 페이지. meta refresh·location.replace 로 game/index.html 로 이동
  COPYING.txt, build-info.json
  game/                    ← 게임 산출물 + 세션 3 셸(web/game/)
    index.html             ← 게임 셸. shell-config.js 의 'taisei.js' 를 script 요소로 동적 주입
    shell.js, shell.css, shell-config.js
    taisei.html, taisei.js, taisei.wasm   ← taisei.html 은 업스트림 셸(직접 열어도 동작)
    data/<sha256> …        ← 리소스 (확장자 없음, 파일 이름 = 내용의 SHA-256)
    background.webp, scythe.webp, favicon.ico, COPYING.txt …
```

Taisei의 Emscripten 빌드가 실제로 요구하는 사항(fork 고정 커밋 `5668c41b` 기준, `src/vfs/emscripten_fetch.c`·`taisei.js`에서 확인):

- `taisei.js`는 `.wasm`을 **스크립트 URL 기준 상대 경로**로 받는다(`new URL(".", scriptSrc)`). `taisei.wasm`은 `taisei.js`와 같은 디렉터리에 있어야 한다.
- 게임 리소스는 런타임에 `emscripten_fetch`로 `data/<content-id>`를 요청한다. 이 경로는 **문서(taisei.html) 기준 상대 경로**이므로 `data/`는 `taisei.html` 옆에 있어야 한다. 모든 리소스가 시작 시 내려받히는 것이 아니라 필요할 때 요청된다.
- 리소스 파일 이름은 내용의 SHA-256이다(정적 리소스 인덱스가 WASM에 포함됨). 확장자가 없으므로 서버는 `application/octet-stream`으로 보내면 된다.
- 설정·리플레이는 Emscripten IDBFS(`/persistent`)에 저장되며 서버와 무관하다.
- `taisei.js`·`taisei.wasm`에 `SharedArrayBuffer`/`PThread`/공유 메모리 플래그가 없다. 즉 pthreads 빌드가 아니며 `Cross-Origin-Opener-Policy`/`Cross-Origin-Embedder-Policy`가 필요하지 않다. 세션 2([#5](https://github.com/kthss01/mini-danmaku-ai-claude/issues/5))가 스레드 빌드로 바꾸면 아래 `--cross-origin-isolation`을 켜고 검사 도구의 `isolation` 항목이 필수로 바뀐다(자동 감지).
- 업스트림 `taisei.html`의 `webgl-debug.js` 참조는 HTML 주석 안에 있어 요청되지 않는다. 검사 도구도 주석 안 태그는 무시한다.

## 서버 실행과 종료

```bash
python scripts/serve-web.py
```

- 기본값: 루트 `build/web/site`, 바인딩 `127.0.0.1`, 포트 `8080`, 디렉터리 진입 파일 `index.html`.
- 시작하면 `serve-web: http://127.0.0.1:8080/ 에서 제공 중 (종료: Ctrl+C)`를 출력한다. 브라우저에서 그 URL을 연다.
- 종료: 터미널에서 `Ctrl+C`. 백그라운드로 띄웠다면 해당 Python 프로세스를 종료한다.

자주 쓰는 옵션:

| 옵션 | 설명 |
| --- | --- |
| `--root <dir>` | 다른 산출물 디렉터리 제공. 예: `--root build/taisei-web` |
| `--index <name>` | 디렉터리 요청 시 제공할 파일. 평면 산출물을 바로 열 때 `--index taisei.html` |
| `--port <n>` | 포트 변경. `--port 0`은 비어 있는 포트를 자동 선택 |
| `--host <addr>` | 바인딩 주소. 기본 `127.0.0.1`(외부 노출 없음) |
| `--cross-origin-isolation` | COOP/COEP 헤더 전송. 스레드 빌드에만 필요 |
| `--quiet` | 요청 로그 생략 |

동작:

- `.wasm` → `application/wasm`, `.js`/`.mjs` → `text/javascript`, `.html` → `text/html`, 확장자 없는 파일 → `application/octet-stream`. OS의 MIME 레지스트리에 의존하지 않도록 스크립트에 고정했다.
- 모든 응답에 `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`. 빌드를 갱신한 뒤 새로고침하면 바로 반영된다.
- 디렉터리 목록을 노출하지 않는다. index 파일이 없는 디렉터리는 404. 슬래시 없는 디렉터리 요청은 301로 `…/`에 안내.
- 루트 밖 경로 차단: `..`, 드라이브 문자, Windows 구분자(`%5c`)가 든 요소가 있으면 404. 루트 안의 symlink/정션이 루트 밖을 가리켜도 resolve 결과가 루트 밖이면 404(디렉터리 index 포함).
- 로컬 개발용이다. HTTP/1.0, Range 요청·압축 미지원. 공개 배포용 서버가 아니다.

오류와 종료 코드:

| 상황 | 메시지 | 종료 코드 |
| --- | --- | --- |
| 루트 디렉터리 없음 | `루트 디렉터리가 없습니다: …` | 2 |
| index 파일 없음 | `index.html 이(가) … 안에 없습니다` (`--index` 안내) | 2 |
| 포트 사용 중·권한 없음 | `포트를 열 수 없습니다 … --port 0 으로 자동 선택하세요` | 3 |
| Ctrl+C | `종료합니다.` | 0 |

### Windows 포트 중복 바인딩 (세션 5 QA-05, 수정 완료)

증상: Windows에서 `python -m http.server` 등이 이미 LISTEN 중인 포트로 `serve-web.py`를 실행하면 종료 코드 3 대신 "제공 중"을 출력하고 계속 실행됐다. 같은 포트에 LISTEN 소켓이 두 개 생기고 요청은 먼저 뜬 서버가 받는다. 세션 5가 #7에 보고했다.

원인(실측, 2026-10-23): 두 번째 소켓이 이미 LISTEN 중인 `127.0.0.1` 포트에 `bind`할 때의 결과.

| 먼저 뜬 소켓 | 나중 소켓 | Windows 11 / Python 3.12.2 | Linux / Python 3.12.15 |
| --- | --- | --- | --- |
| `SO_REUSEADDR` | `SO_REUSEADDR` | **bind 성공(중복 LISTEN)** | 거부 errno 98 |
| 옵션 없음 | `SO_REUSEADDR` | 거부 WinError 10013 | 거부 errno 98 |
| `SO_REUSEADDR` | `SO_EXCLUSIVEADDRUSE` | 거부 WinError 10048 | 해당 없음 |
| `SO_EXCLUSIVEADDRUSE` | `SO_REUSEADDR` | 거부 WinError 10013 | 해당 없음 |

표준 `http.server.HTTPServer`는 `allow_reuse_address = 1`이라 `SO_REUSEADDR`를 켠다. `python -m http.server`와 수정 전 `serve-web.py`가 둘 다 켜므로 첫 줄 조합이 되어 Windows에서만 중복 LISTEN이 됐다. 수정 전 테스트는 옵션 없는 소켓으로 포트를 막아 둘째 줄 조합만 확인했기 때문에 이 경우를 놓쳤다.

수정: Windows에서는 서버 클래스(`WebAssetsServer`)가 `SO_REUSEADDR`를 끄고 `SO_EXCLUSIVEADDRUSE`로 bind한다. 먼저 뜬 서버의 옵션과 관계없이 bind가 실패해 종료 코드 3으로 끝나고, 우리 서버가 먼저 떠 있으면 나중 서버도 들어오지 못한다. Linux는 표준 동작을 그대로 쓴다. 요청 20건을 처리하고 닫은 뒤 같은 포트에 즉시 다시 bind되는 것도 확인했다.

수정 전후를 실제 프로세스로 비교했다. `python -m http.server <port>`를 먼저 띄우고 `serve-web.py --port <port>`를 실행한 결과다.

| 환경 | 수정 전 | 수정 후 |
| --- | --- | --- |
| Windows 11 / 3.12.2 | 5초 뒤에도 실행 중, "제공 중" 출력, LISTEN 소켓 2개, `GET /`은 기존 서버 응답 | 종료 코드 3(WinError 10048), LISTEN 1개, 기존 서버 응답 유지 |
| Linux / 3.12.15 | 종료 코드 3(errno 98) | 종료 코드 3(errno 98) |

회귀 테스트(`test_serve_web.py`)는 수정 전 코드에서 5개가 실패한다. 표준 서버 점유 시 bind 거부, 우리 서버 점유 시 bind 거부, Windows 소켓 옵션, 실제 프로세스 2종(표준 서버 점유·우리 서버 이중 실행)의 종료 코드 3이다. 프로세스 내 테스트는 `main()` 대신 `create_server`의 예외만 확인한다. 회귀로 bind가 성공하면 `serve_forever`에서 멈추기 때문이며, 실제로 수정 전 코드로 `main()`을 부르던 초기 테스트가 3시간 멈춘 일이 있었다. 종료 코드는 30초 제한이 있는 프로세스 테스트가 확인한다.

## 리소스 검사 도구

```bash
# 정적 검사만
python scripts/check-web-assets.py --root build/web/site

# 서버를 띄운 뒤 HTTP 검사까지
python scripts/serve-web.py --root build/web/site --port 8080        # 터미널 1
python scripts/check-web-assets.py --root build/web/site --url http://127.0.0.1:8080   # 터미널 2

# 리소스 내용 해시 전부 검증 + 전체 리소스 HTTP 요청 + JSON 기록(느림, 200 MiB 이상 읽음)
python scripts/check-web-assets.py --root build/web/site --url http://127.0.0.1:8080 --verify-hashes --sample-data -1 --json build/web/check.json
```

정적 검사(파일 시스템):

- 진입 HTML(`--entry`, 기본 `index.html`)에서 `script/link/img/a/source/css url()` 참조를 따라가며 로컬 파일 존재를 확인한다. 로컬 `.html` 링크는 재귀적으로 따라간다.
- 대소문자가 다른 참조는 오류(`case-mismatch`). Windows에서는 열리지만 Linux 서버·공개 호스팅에서는 404가 된다.
- `/`로 시작하는 절대 경로 참조는 오류(`absolute-path`). 하위 경로 배포를 깨뜨린다.
- `<meta http-equiv="refresh" content="…; url=…">` 이동 대상도 HTML 링크처럼 따라간다.
- JS 문자열의 `.wasm`/`.data` 참조는 스크립트 기준 상대 경로로 확인한다(Emscripten `locateFile` 동작).
- JS 문자열의 `.js` 참조(예: 세션 3 셸의 `shell-config.js`에 있는 `'taisei.js'`)는 `document.createElement('script')`로 주입되는 로더로 보고, 그 JS를 실행하는 **HTML 문서 기준** 상대 경로로 확인한 뒤 재귀적으로 따라간다. 파일이 없으면 오류다.
- 한계: 문자열 결합으로 경로를 만드는 경우(예: `gameBase: 'game/'` + `'taisei.js'`)는 각 조각만 보이므로 추적하지 못한다. 현재 셸은 `gameBase: ''`이라 해당하지 않는다. 이런 구조로 바뀌면 `--require-wasm`이 놓침을 오류로 드러낸다.
- `--require-wasm`: 진입에서 `.wasm`에 도달하지 못하면 경고 대신 오류로 처리한다. 게임 산출물 검증에는 항상 켠다.
- `.wasm` 매직·버전·섹션 구조를 파싱하고 공유 메모리(pthreads) 사용 여부를 판정한다.
- WASM 안의 `data/%s` 문자열로 리소스 요청 경로를 확인하고, `data/` 파일 이름이 SHA-256인지, `--verify-hashes`면 내용과 일치하는지 확인한다.

HTTP 검사(`--url`):

- 진입 HTML 자체가 200·`text/html`·파일과 같은 길이로 오는지(`--root`와 `--url`이 다른 산출물을 가리키면 여기서 실패).
- 진입 디렉터리 요청이 `index.html`을 `text/html`로 돌려주는지.
- 참조된 모든 리소스가 200, 확장자에 맞는 Content-Type, 파일 크기와 같은 본문 길이인지.
- `data/` 리소스 표본(`--sample-data`, 기본 3, `-1`은 전체)이 200이고 `text/html`이 아닌지(SPA fallback 오설정 검출).
- 없는 경로와 없는 `.wasm`에 정확히 404를 돌려주는지(HTML fallback이면 `instantiateStreaming` 오류 원인이 숨는다).
- COOP/COEP: `--require-isolation auto`(기본)는 스레드 사용이 감지될 때만 필수로 본다. `yes`/`no`로 강제할 수 있다.
- 참고 정보로 `Cache-Control`, `X-Content-Type-Options`를 기록한다.
- 연결 거부·응답 없이 끊김 같은 요청 실패는 traceback 대신 `http-error` finding으로 기록하고 종료 코드 1로 끝난다.

종료 코드: 0 오류 없음, 1 오류 있음, 2 사용법 오류. `--json`으로 전체 결과(findings, resources, http_checks)를 저장한다.

## fixture 검증 (서버·도구 자체 검증)

실제 게임 없이 `tests/web-server/fixture/site`(진입 `index.html`, `game/game.html`·`game.js`·최소 `game.wasm`, 해시 이름 리소스 2개)로 서버와 도구를 검증한다. 이는 도구의 동작 검증이지 게임 산출물 검증이 아니다.

```bash
python -m unittest discover -s tests/web-server -t tests/web-server -v
```

결과(2026-10-24): 55개 테스트.

| 환경 | 결과 |
| --- | --- |
| Windows 11, Python 3.12.2 | 54 통과, 1 skip(일반 사용자 권한으로 symlink 생성 불가, WinError 1314) |
| Linux, Docker `python:3.12-slim`(3.12.15), `docker run --rm -v <clone>:/work -w /work python:3.12-slim python -m unittest discover -s tests/web-server -t tests/web-server` | 54 통과(symlink 테스트 포함), 1 skip(Windows 전용 소켓 옵션 확인) |

포함 항목: index 제공, WASM/JS MIME, 중첩 상대 경로, 404, `no-store`/`nosniff`, 격리 헤더 on/off, 디렉터리 목록 차단, 경로 탈출 방지(`..`, 인코딩 역슬래시, 중첩 상위 경로, 루트 밖 symlink 파일·디렉터리), `--index`, 루트 부재·index 부재·포트 충돌 종료 코드(표준 서버·우리 서버가 점유한 포트, 실제 프로세스 2종, 포트 반환), 문서 명령 그대로 자식 프로세스 실행·종료, 검사 도구의 누락·대소문자(추적 중단, Linux에서도 crash 없음)·절대 경로·루트 탈출·해시 불일치·잘못된 WASM·스레드 빌드 감지·잘못된 MIME 서버·HTML fallback 서버·진입 HTML 404(루트·중첩)·응답 없이 끊는 서버·접속 불가 검출, 동적 주입 로더 추적(문서 기준 해석, 누락 시 오류)·meta refresh 추적·`--require-wasm`.

## 공식 산출물 검증 (세션 1·3 머지 후)

세션 1 PR #11(머지 `03f580b`)과 세션 3 PR #12(머지 `1ad54ea`)가 main에 들어간 뒤, 새 디렉터리에서 문서 명령 그대로 빌드·서빙·검사했다(아래 1번). 이어서 세션 1 PR #15(머지 `fd9e00e`)가 Taisei gitlink를 `f59212b7`(세션 2 fork PR #1 포함)로 올렸으므로 같은 clone을 `fd9e00e`로 갱신해 `-Force`로 다시 빌드·검사했다(아래 2번). 아래 표는 최신 `fd9e00e` 기준이다.

```powershell
# 1) 새 clone 첫 빌드 (03f580b 검증에 사용): 옵션 없이 실행, 270초(emsdk 캐시 사용)
git clone --recurse-submodules https://github.com/kthss01/mini-danmaku-ai-claude.git
cd mini-danmaku-ai-claude
.\scripts\build-web.ps1

# 2) 같은 clone을 새 main으로 갱신한 두 번째 빌드 (fd9e00e 검증에 사용): 기존 build/web/install 이 있어 -Force 필요, 255초
git pull --ff-only
git submodule update --init --recursive
.\scripts\build-web.ps1 -Force

# 서빙과 검사 (두 경우 공통)
python scripts/serve-web.py                       # 기본 루트 build/web/site, http://127.0.0.1:8080/
python scripts/check-web-assets.py --entry index.html       --url http://127.0.0.1:8080 --require-wasm --verify-hashes --sample-data -1 --json build/web/check/index_html.json
python scripts/check-web-assets.py --entry game/index.html  --url http://127.0.0.1:8080 --require-wasm --verify-hashes --sample-data -1 --json build/web/check/game_index_html.json
python scripts/check-web-assets.py --entry game/taisei.html --url http://127.0.0.1:8080 --require-wasm --verify-hashes --sample-data -1 --json build/web/check/game_taisei_html.json
```

출처(`build/web/site/build-info.json`):

| 항목 | 값 |
| --- | --- |
| 메인 커밋 | `fd9e00ea087f2b4f3606755ddace7f5bc2f8c00c`, 미커밋 변경 없음(`repositoryDirtyEntries: []`, `webShellDirtyEntries: []`) |
| Taisei fork | `f59212b72df3b68459b4677a6200e42be700078a`, 미커밋 변경 없음 |
| 도구 | emsdk 5.0.3, `taiseiproject/linux-toolkit:20260804@sha256:1104b4a5…74b2` |
| 빌드 시각 | 2026-10-23T13:06:27Z 시작, 패키징 13:10:30Z (`BuildAndPackage`) |
| site | 진입 `game/index.html`, 549개 파일(build-info 제외), 222,408,181 B |
| `build-info.json` SHA-256 | `ec8eef2cbd763d912509b7bb68b0c305da786d21c1fb28c217172847a3906a92` |
| `game/taisei.wasm` | 4,539,198 B, `1eb2168135b22c2d2a2d37e09e04f3ef96d073b6013120a8b4749feaaea0c1ad` |
| `game/taisei.js` | 101,107 B, `d49ca968c16d0a69cc275f21a2f537db51c151a25401781c911149c328c73a01` |
| `game/index.html` | `0a8b31f86be3f7b53cce0d3ae88d7d49ea5ac02e5c652597ab4d439596c08f2d` |
| `game/data/` | 529개, 217,186,447 B. 목록 매니페스트(이름순 `<이름> <크기>` 줄을 LF로 이어 붙인 텍스트의 SHA-256) `aa172eaf613c3e7e39bfd142b5a58b64cf7f8d55be512eaa9a0f11217ddfa3db` |

직전 main `03f580b`(Taisei `5668c41b`) 산출물: site 549개 222,407,535 B, `taisei.wasm` 4,538,726 B `3c43a6b1…4192`, `taisei.js` `3e7ed5b7…8d64`, `build-info.json` `f9535df8…8484`. `data/` 매니페스트는 위와 같다.

`fd9e00e`의 `taisei.js`는 세션 1이 #4에 인계한 값(`d49ca968…`)과 같고, `taisei.wasm`은 세션 1 빌드(`76f6b39d…`)와 다르다. 세션 1이 기록한 대로 wasm 바이트 재현성은 보장되지 않는다. `data/` 이름·크기 목록은 모든 빌드에서 같다.

검사 결과(`fd9e00e`, `03f580b` 모두 같은 수치):

| 진입 | 참조 리소스 | HTTP 검사 | 결과 |
| --- | --- | --- | --- |
| `index.html`(서빙 루트) | 9 | 543건 실패 0 | 통과, 오류 0·경고 0 |
| `game/index.html`(세션 3 셸) | 8 | 542건 실패 0 | 통과, 오류 0·경고 0 |
| `game/taisei.html`(업스트림 셸) | 5 | 539건 실패 0 | 통과, 오류 0·경고 0 |

- 세 진입 모두 `game/taisei.wasm`(유효, 섹션 11개, 공유 메모리 없음)과 `game/data/` 529개에 도달했고, 529개 모두 이름과 내용 SHA-256이 일치했다(정적·HTTP 양쪽).
- 루트는 `<a href="game/index.html">`·meta refresh로 셸에 닿고, 셸은 `shell-config.js`의 `'taisei.js'`를 문서 기준으로 풀어 `game/taisei.js` → `game/taisei.wasm`으로 이어진다. `data/` 위치는 로더를 실행하는 문서(`game/index.html`) 기준 `game/data/`로 판정됐다.
- `GET /` → `index.html`, `GET /game/` → `game/index.html`(200 `text/html`), 없는 경로·없는 `.wasm` → 404, `.wasm` → `application/wasm`, 전 응답 `no-store`·`nosniff`, COOP/COEP 없음(스레드 미사용이라 불필요).
- 이 수정 전 검사기(PR #10 버전)는 `game/index.html` 진입에서 동적 주입 로더를 따라가지 못해 WASM·`data/`를 검사하지 않고 경고 1건으로 통과시켰다(`fd9e00e` 산출물에서도 재현). 이 문서의 결과는 수정된 검사기 기준이다.

브라우저 확인(Claude 데스크톱 내장 Chromium, `03f580b` 산출물): `http://127.0.0.1:8080/`을 열면 `game/index.html`로 이동했고 시작 버튼을 누르자 인트로 장면(The Hakurei Shrine)까지 렌더링됐다. 리소스 250건 중 4xx/5xx 0건, `game/taisei.js`·`game/taisei.wasm`(4,538,726 B) 200, `data/` 요청 244건 모두 `/game/data/` 아래였다. 확인 시점에 버퍼에 남은 콘솔 오류는 0건이었으나 앞선 로그 888건은 버퍼에서 밀려나 확인하지 못했다. 조작·소리·플레이 판정은 세션 5 범위다. `fd9e00e` 산출물의 브라우저 진입은 세션 1·2가 #4·#5에 기록했으며 이 세션에서는 다시 하지 않았다.

## 탐색 검증: 기존 로컬 빌드 (공식 산출물 이전)

대상: 기존 `feat/web-playable` 로컬 작업(`scripts/build-web.ps1`, 공식 CI 이미지 + emsdk 5.0.3)으로 만든 `build/taisei-web`. Taisei fork 커밋 `5668c41b41f7227d21fc80cf56997d4d30356ce7`. 이 산출물을 세션 4 clone의 `build/`(Git 제외)로 복사해 검사했다. 공식 산출물 검증은 위 절에 있으며, 이 절은 그 전에 수행한 탐색 검증 기록이다.

산출물 구성: `taisei.html` 12,168 B, `taisei.js` 100,933 B, `taisei.wasm` 4,538,726 B, `data/` 529개 207.1 MiB, `background.webp`, `scythe.webp`, `favicon.ico`, `COPYING.txt`, 문서 텍스트·HTML, 그리고 `web/index.html`(현재 로컬 셸).

### 1) 평면 배치 (현재 build-web.ps1 출력 그대로)

```bash
python scripts/serve-web.py --root build/real-taisei-web --port 8765 --quiet
python scripts/check-web-assets.py --root build/real-taisei-web --url http://127.0.0.1:8765 --verify-hashes --sample-data -1 --json build/web/check-real-flat.json
```

결과: **통과 (오류 0, 경고 0)**. HTTP 검사 541건(진입 페이지 1 + index 1 + 리소스 7 + data 529 + 404 프로브 2 + 격리 헤더 1) 모두 성공. Codex 검토 반영 후 같은 명령으로 재검사해 동일하게 통과했다.

- `index.html → taisei.html → taisei.js → "taisei.wasm"` 참조 체인과 `background.webp`, `scythe.webp`, `favicon.ico`, `COPYING.txt` 존재·대소문자 일치.
- `taisei.wasm` 유효, 섹션 11개, 공유 메모리 없음 → 스레드 요구 없음, COOP/COEP 불필요.
- `data/` 529개 파일 모두 이름이 내용의 SHA-256과 일치(정적 검증), HTTP로 전부 받아 본문 해시 재확인.
- `GET /taisei.wasm` → `200`, `Content-Type: application/wasm`, `Content-Length: 4538726`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.
- `GET /nope.wasm` → `404`, `GET /data/` → `404`(목록 비노출).

브라우저 확인(Claude 데스크톱 내장 브라우저, Chromium 기반): `http://127.0.0.1:8765/taisei.html`을 열어 타이틀 화면까지 로딩됨. `performance` 리소스 항목 250개 중 실패 0건, `taisei.wasm` 4,538,726 B `200`, 콘솔 오류 0건(업스트림 WebGL `GL_INVALID_VALUE` 경고는 있으나 서버와 무관). 조작·사운드·플레이 판정은 세션 5 범위이며 여기서는 하지 않았다.

### 2) 중첩 배치 (세션 1 제안 구조)

루트에 임시 `index.html`(`game/taisei.html` 링크만 포함)을 두고 게임 산출물을 `game/` 아래로 옮겨 검사했다.

```bash
python scripts/serve-web.py --root build/real-nested --port 8766 --quiet
python scripts/check-web-assets.py --root build/real-nested --url http://127.0.0.1:8766 --sample-data 5 --json build/web/check-real-nested.json
```

결과: **통과 (오류 0, 경고 0)**. HTTP 검사 15건 성공. `game/taisei.wasm` → `application/wasm`, `game/data/` 529개 인식, `GET /game/` → 404(index 없음, 목록 비노출), 상대 경로가 하위 디렉터리에서도 그대로 풀린다. 실제 셸의 링크·경로는 세션 3 산출물로 확정된다.

## 공개 배포 시 필요한 조건

GitHub Pages 배포는 이 조건을 기준으로 한다. 절차는 [PAGES.md](PAGES.md)에 있다.

| 조건 | 내용 |
| --- | --- |
| MIME | `.wasm` → `application/wasm`(필수, `instantiateStreaming`), `.js` → `text/javascript`, 확장자 없는 `data/*` → `application/octet-stream` |
| 404 | 없는 경로에 200 HTML fallback(SPA 설정)을 쓰지 말 것. `data/` 요청 실패가 숨는다 |
| 경로 | 모든 참조가 상대 경로이므로 하위 경로(`/taisei/`) 배포 가능. 파일 이름 대소문자 보존 |
| 헤더 | 현재 빌드는 COOP/COEP 불필요. pthreads 빌드로 바뀌면 `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Embedder-Policy: require-corp` 필요하고 외부 리소스는 CORP/CORS를 맞춰야 함 |
| 캐시 | `data/<sha256>`는 내용 주소이므로 장기 캐시(immutable) 가능. `taisei.html/js/wasm`은 재검증 필요 |
| 압축 | `wasm`/`js`는 gzip/brotli 효과 큼. `data/*`는 이미 압축된 리소스가 많음 |
| 용량 | 약 212 MiB(리소스 포함). 리소스는 필요 시 요청되므로 초기 전송량은 더 작음 |
| 고지 | `COPYING.txt`와 음악·이미지 고지 포함 여부는 세션 1·5 확인 |

## 미검증·남은 사항

- 공식 산출물 검증은 Windows 한 대(이 PC)에서만 수행했다. 다른 PC·Linux 호스트에서의 빌드·서빙 재현은 세션 5 범위다.
- 검사기는 문자열 결합으로 만든 로더 경로를 추적하지 못한다. `--require-wasm`으로 놓침을 오류로 드러낸다.
- 브라우저 조작·사운드·플레이·저장 검증은 세션 5 범위다.
- 서버는 HTTP/1.0 단순 정적 서버다. 공개 호스팅은 별도 결정 후 진행한다.
- `scripts/README.md`에 두 스크립트 항목을 추가하는 일은 공용 파일이므로 세션 5 통합 문서에 맡긴다.
