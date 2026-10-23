# 웹 산출물 로컬 HTTP 제공과 리소스 검사

담당: 세션 4 ([이슈 #7](https://github.com/kthss01/mini-danmaku-ai-claude/issues/7)), 부모 [#2](https://github.com/kthss01/mini-danmaku-ai-claude/issues/2)
검증일: 2026-10-23

Taisei 웹 빌드(HTML/JS/WASM/리소스)를 로컬에서 제공하는 명령과, 산출물의 파일 참조·경로·MIME·HTTP 헤더를 검사하는 도구를 정리한다. 공개 배포는 범위에 포함하지 않는다. 로컬 URL(`http://127.0.0.1:…`)은 공개 URL이 아니다.

## 요약

| 항목 | 결과 |
| --- | --- |
| 서버 명령 | `python scripts/serve-web.py` (기본 루트 `build/web/site`, `127.0.0.1:8080`) |
| 검사 명령 | `python scripts/check-web-assets.py --root <산출물> [--url http://127.0.0.1:8080]` |
| WASM MIME | `application/wasm` 제공·검사 확인 |
| 스레드(pthreads) | 현재 빌드는 사용하지 않음 → COOP/COEP 격리 헤더 불필요(옵션으로 제공) |
| 리소스 경로 | `data/<sha256>` 상대 경로, 529개 207.1 MiB, 내용 해시 전부 일치 |
| fixture 테스트 | 43개: Windows 42 통과 + symlink 권한 없어 1 skip, Linux(Docker python:3.12) 43 통과 (`tests/web-server`) |
| 실제 산출물 검사 | 평면·중첩 두 배치 모두 통과(HTTP 541건), 브라우저에서 타이틀 화면까지 로딩 확인 |

## 전제: 산출물 구조

세션 1([#4](https://github.com/kthss01/mini-danmaku-ai-claude/issues/4))이 제안한 공통 계약은 다음과 같다. 세션 1 댓글로 확정되기 전까지 이 문서는 이 구조를 기본값으로 둔다.

```text
build/web/site/            ← 서빙 루트 (--root 기본값)
  index.html               ← 세션 3 웹 셸 (web/ 를 루트로 복사)
  game/                    ← 게임 산출물
    taisei.html, taisei.js, taisei.wasm
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
- JS 문자열의 `.wasm`/`.data` 참조를 스크립트 기준 상대 경로로 확인한다.
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

결과(2026-10-23): 43개 테스트.

| 환경 | 결과 |
| --- | --- |
| Windows 11, Python 3.12.2 | 42 통과, 1 skip(일반 사용자 권한으로 symlink 생성 불가, WinError 1314) |
| Linux, Docker `python:3.12-slim`(3.12.15), `docker run --rm -v <clone>:/work -w /work python:3.12-slim python -m unittest discover -s tests/web-server -t tests/web-server` | 43 통과(symlink 테스트 포함) |

포함 항목: index 제공, WASM/JS MIME, 중첩 상대 경로, 404, `no-store`/`nosniff`, 격리 헤더 on/off, 디렉터리 목록 차단, 경로 탈출 방지(`..`, 인코딩 역슬래시, 중첩 상위 경로, 루트 밖 symlink 파일·디렉터리), `--index`, 루트 부재·index 부재·포트 충돌 종료 코드, 문서 명령 그대로 자식 프로세스 실행·종료, 검사 도구의 누락·대소문자(추적 중단, Linux에서도 crash 없음)·절대 경로·루트 탈출·해시 불일치·잘못된 WASM·스레드 빌드 감지·잘못된 MIME 서버·HTML fallback 서버·진입 HTML 404(루트·중첩)·응답 없이 끊는 서버·접속 불가 검출.

## 실제 게임 산출물 검증

대상: 기존 `feat/web-playable` 로컬 작업(`scripts/build-web.ps1`, 공식 CI 이미지 + emsdk 5.0.3)으로 만든 `build/taisei-web`. Taisei fork 커밋 `5668c41b41f7227d21fc80cf56997d4d30356ce7`. 이 산출물을 세션 4 clone의 `build/`(Git 제외)로 복사해 검사했다. 세션 1의 공식 산출물이 머지되면 같은 명령으로 재검증한다.

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

## 공개 배포 시 필요한 조건 (문서화만, 배포하지 않음)

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

- 세션 1의 공식 `build/web/site` 산출물과 세션 3 셸의 실제 링크 경로는 아직 없다. 머지 후 `python scripts/check-web-assets.py --root build/web/site --url …`로 재검증해야 한다.
- 브라우저 조작·사운드·플레이·저장 검증은 세션 5 범위다.
- 서버는 HTTP/1.0 단순 정적 서버다. 공개 호스팅은 별도 결정 후 진행한다.
- `scripts/README.md`에 두 스크립트 항목을 추가하는 일은 공용 파일이므로 세션 5 통합 문서에 맡긴다.
