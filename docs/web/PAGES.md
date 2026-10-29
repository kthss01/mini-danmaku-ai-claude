# GitHub Pages 배포

공개 주소: https://kthss01.github.io/mini-danmaku-ai-claude/
워크플로: [`.github/workflows/pages.yml`](../../.github/workflows/pages.yml)

로컬과 같은 `scripts/build-web.ps1`을 GitHub Actions의 Linux 러너에서 실행하고, 그 결과 `build/web/site/`를 그대로 GitHub Pages에 올린다. 산출물 계약은 [BUILD.md](BUILD.md), 공개 호스팅 조건은 [SERVING.md](SERVING.md)의 "공개 배포 시 필요한 조건"을 따른다.

## 저장소 설정

| 항목 | 값 |
| --- | --- |
| Settings → Pages → Source | GitHub Actions |
| `github-pages` 환경 배포 브랜치 | `main`만 허용 |

`main` 이외 브랜치에서는 배포 작업이 환경 정책에 막힌다. 그래서 PR에서는 빌드와 정적 검사만 한다.

## 실행 조건

| 이벤트 | 수행 내용 |
| --- | --- |
| `main` push | 빌드 → 정적 검사 → 배포 → 배포 주소 HTTP 검사 |
| `pull_request` | 빌드 → 정적 검사(배포하지 않음) |
| 수동 실행(`workflow_dispatch`) | `main`에서 실행하면 `main` push와 같음 |

push·PR은 아래 경로가 바뀔 때만 실행한다. 문서만 바꾼 커밋은 다시 빌드하지 않는다.

- `.github/workflows/pages.yml`
- `configs/web-build/**`
- `game/taisei`(submodule 커밋 갱신)
- `scripts/build-web.ps1`, `scripts/check-web-assets.py`
- `web/**`

## 작업 구성

1. **build**
   - `game/taisei` submodule만 체크아웃한다. Taisei 내부 submodule은 빌드 컨테이너가 직접 받는다.
   - `pwsh ./scripts/build-web.ps1`로 빌드하고 패키징한다. 로컬과 같은 이미지, 같은 emsdk 버전을 쓴다.
   - `check-web-assets.py --require-wasm --verify-hashes`로 참조·경로·대소문자·WASM 형식·리소스 해시를 확인한다.
   - 실행 요약(Summary)에 `build-info.json`의 Taisei 커밋, 메인 커밋, Emscripten 버전, 파일 수와 크기를 남긴다.
   - `main`에서는 `build/web/site/`를 Pages 산출물로 업로드한다.
2. **deploy**: `actions/deploy-pages`로 `github-pages` 환경에 배포한다.
3. **verify**
   - 업로드한 산출물을 다시 받아 푼다.
   - 배포 주소에 `check-web-assets.py --url`로 실제 요청을 보낸다.
   - 상태 코드, MIME(`.wasm` → `application/wasm`), 404 동작, 디렉터리 index를 확인한다.

## 로컬 빌드와 다른 점

- **러너 상태:** 러너는 매번 새로 시작한다. emsdk Docker volume 캐시가 없어서 매 실행마다 emsdk와 LLVM을 다시 내려받는다.
- **빌드 출처의 dirty 기록:** 체크아웃이 깨끗하므로 `build-info.json`의 dirty 목록은 비어 있어야 한다.
- **Taisei 버전 문자열:** submodule을 얕게(depth 1) 받아서 git 태그가 없다. 그래서 Taisei는 기본 버전 문자열을 쓴다. 로컬 clone에도 태그가 없어 결과는 같다.
- **스크립트 조정:** Linux에서도 돌도록 두 곳을 고쳤다.
  - `build-web.ps1`의 하위 경로 구분자를 `/`로 바꿨다. Windows PowerShell에서도 같은 경로로 풀린다.
  - `container-build.sh`에 `safe.directory` 설정을 추가했다. 마운트한 저장소의 소유자(러너 사용자)와 컨테이너 사용자(root)가 달라 생기는 Git 소유권 거부를 피하기 위해서다.

## 공개 배포 시 주의

- **저장 데이터:** 설정·리플레이·리소스 캐시는 방문자 브라우저의 IndexedDB에 저장된다. 서버에는 아무것도 저장하지 않는다. 저장소는 주소(origin)별로 따로라서, 로컬 `127.0.0.1:8080`의 저장 데이터는 공개 주소로 넘어오지 않는다.
- **첫 실행 다운로드:** 처음 실행할 때 리소스 약 207 MB를 내려받는다. 로컬보다 오래 걸릴 수 있다.
- **캐시 헤더:** GitHub Pages는 캐시 헤더를 바꿀 수 없다. `data/<sha256>`의 장기 캐시는 브라우저 기본 동작과 IndexedDB 캐시에 맡긴다.
- **COOP/COEP:** 현재 빌드는 pthreads를 쓰지 않아 이 헤더가 필요 없다. 스레드 빌드로 바꾸면 GitHub Pages에서는 이 헤더를 설정할 수 없으므로 배포 방식을 다시 정해야 한다.
- **라이선스:** 사이트 루트와 `game/`에 `COPYING.txt`가 들어간다. 음악·이미지별 출처 표기는 [WEB_SETUP.md](../WEB_SETUP.md) 8절을 따른다.

## 검증 결과

2026-10-29에 확인했다(#29). 공개 주소 결과는 로컬 공식 QA([QA.md](QA.md))와 따로 기록한다. #2 완료 판정(로컬 기준)에 쓸지는 #2·#8에서 정한다.

### PR 빌드 — [run 40861344584](https://github.com/kthss01/mini-danmaku-ai-claude/actions/runs/40861344584)

- 대상: PR #26 head `67f2ae9`, `pull_request` 이벤트, 10:55~11:00 UTC
- build 작업 성공: Linux 러너에서 `build-web.ps1` 빌드·패키징과 `check-web-assets.py --require-wasm --verify-hashes`가 통과했다.
- deploy·verify는 PR이라 설계대로 건너뛰었다.

### main 첫 배포 — [run 40862185693](https://github.com/kthss01/mini-danmaku-ai-claude/actions/runs/40862185693)

- 대상: 머지 커밋 `0387c04`, `push` 이벤트, 11:01~11:06 UTC. build·deploy·verify 모두 성공했다.
- 빌드 스크립트 실행: 11:02:10~11:05:54 UTC(약 3분 44초, `build-info.json` 기준)
- verify: 배포 주소에 HTTP 요청 17건, 실패 0·오류 0·경고 0. 유효한 WASM(4,539,198 bytes, 섹션 11개), 리소스 529개(207.1 MiB), 디렉터리 index, `game/data/` 표본 3개, 없는 경로와 없는 `.wasm`의 404, `Cache-Control: max-age=600`을 확인했다. 스레드를 쓰지 않는 빌드라 COOP/COEP는 필요 없다.
- 실행 주석: 세 작업 모두 같은 종류의 경고·알림이 붙었고, 이번 결과에는 영향이 없다.
  - 경고: Node.js 20 대상 액션(`checkout@v4`, `configure-pages@v5`, `upload-artifact@v4`, `deploy-pages@v4`, `download-artifact@v4`)을 Node.js 24로 강제 실행한다.
  - 알림: `ubuntu-latest`가 Ubuntu 26으로 바뀌는 중이다. 이번 실행은 Ubuntu 24.04 이미지(20261025.353)였다.

### 공개 주소 응답 (11:25 UTC)

| 경로 | 응답 |
| --- | --- |
| `/` | 200 `text/html`. meta refresh와 `location.replace`로 `game/index.html`로 넘긴다 |
| `/game/`, `/game/index.html` | 200 `text/html` |
| `/COPYING.txt`, `/game/COPYING.txt` | 200 `text/plain`, 2,478 bytes, 두 파일 내용 같음 |
| `/build-info.json` | 200 `application/json` |
| `/game/taisei.js` | 200 `application/javascript` |
| `/game/taisei.wasm` | 200 `application/wasm` |
| 없는 경로 | 404 |

404를 뺀 응답은 모두 `Cache-Control: max-age=600`이다.

공개된 `build-info.json`의 내용은 다음과 같다.

- 커밋: Taisei `f59212b72df3b68459b4677a6200e42be700078a`, 메인 저장소 `0387c04a39ed3cb240f016a69c9431a4d8b66c50`(build·packaging 같음)
- dirty 목록 4개(`build.repositoryDirtyEntries`, `build.taiseiWorktreeDirtyEntries`, `packaging.repositoryDirtyEntries`, `packaging.webShellDirtyEntries`)가 모두 `[]`
- Emscripten 5.0.3, 빌드 이미지 `taiseiproject/linux-toolkit:20260804@sha256:1104b4a5…`
- 리소스 529개 217,186,447 bytes(내용 주소 방식), 사이트 파일 549개 222,407,196 bytes(`build-info.json` 제외)

### 공개 주소 브라우저 플레이 (11:26~11:34 UTC)

- 환경: Windows 11 Home, Claude 데스크톱 앱 내장 브라우저(Chromium 152.0.7977.167), 패널이 화면에 보이는 상태. 사람이 조작한 Chrome이 아니다.
- 입력: 메뉴 이동과 Z·X·Esc는 브라우저 키 입력으로 한 번씩 눌렀다. 자동화 도구는 키를 누른 채 유지하지 못한다. 그래서 이동·연사·저속은 캔버스에 DOM 키 이벤트(`keydown` → 0.4~1.4초 → `keyup`)를 보내 확인했다.

| 항목 | 결과 |
| --- | --- |
| 시작 | "게임 시작" → "리소스를 미리 내려받는 중 (N/1016)" → 16초에 897/1016, 24초 안에 끝나고 인트로 컷신 시작 |
| 메뉴 | 인트로를 Z로 넘김 → 메인 메뉴 → Start Story → Easy → 레이무(Yōkai Buster) |
| 스테이지 진입 | Stage 1 "Misty Lake Encounter" 시작, BGM 제목 표시 |
| 이동 | 오른쪽 0.7초 → 화면 오른쪽 끝, 왼쪽 1.4초 → 왼쪽 끝으로 이동 |
| 공격 | Z를 누르는 동안 샷이 연속으로 나감 |
| 저속 | Shift를 누르는 동안 캐릭터 둘레에 원형 표시가 나타남. 중앙 판정 점은 이 해상도에서 판별하지 않았다 |
| 봄 | X → 스펠 카드 발동 연출, Spell Cards 3 → 2 |
| 일시정지 | Esc → "Game Paused" 메뉴, Esc로 복귀 |
| 게임 오버 | Continue, Restart the Game 동작 |
| HUD FPS | 패널이 앞에 있을 때 59.88~60.03 fps. 다른 탭을 앞에 둔 동안은 3.72 fps(백그라운드 탭 갱신 억제, #28) |
| 콘솔 | 읽을 수 있었던 최근 버퍼에는 오류가 없고, `FS.syncfs operations in flight at once` 경고만 반복됐다(#28). 앞선 674건은 버퍼에서 밀려나 읽지 못했다 |

### 공개망 조건

- **완전한 첫 방문이 아니었다.** 이 브라우저 프로필에는 같은 날 앞서 공개 주소를 열 때 생긴 저장 데이터(IndexedDB `/persistent`, 97.0 MB)가 있었다. 엔진은 캐시에 없는 리소스를 내려받아 `/persistent/res-cache/`에 저장했고, 확인을 마친 11:32 UTC에 사용량은 217.8 MB였다.
- 시작 후 15초 동안 `game/data/` 244개, 70.6 MB를 HTTP/2로 받았다(Resource Timing 기준). 브라우저 타이밍 버퍼(250건)가 차서 그 뒤 요청은 집계하지 못했다. `taisei.wasm`은 압축 전송으로 1.7 MB(원본 4.5 MB)를 받았다.
- 응답이 멈춘 연결(#28 stall)은 이번 실행에서 나타나지 않았다. fetch timeout을 설정하지 않은 상태 자체는 그대로다(#28).

### 라이선스 고지

- 루트와 `game/`의 `COPYING.txt`가 공개 주소에서 열린다(200 `text/plain`, 내용 같음, 브라우저에서 UTF-8로 표시).
- 셸 하단 "라이선스 고지" 링크는 새 탭으로 `game/COPYING.txt`를 연다. 내장 브라우저가 자동 입력으로 여는 새 탭을 막아, 링크 주소로 직접 이동해 열리는 것을 확인했다.
- `COPYING.txt`에는 Taisei 코드 라이선스(MIT 형식), 사운드트랙(Tuck V, CC-BY 4.0)과 캐릭터 초상화(afensorm, CC-BY 4.0)의 출처·링크, 배경 사진 출처가 있다. [WEB_SETUP.md](../WEB_SETUP.md) 8절의 설명과 맞는다.

### 확인하지 않은 것

- 소리, 사람이 조작하는 Chrome에서의 FPS·창 전환(Alt+Tab)·전체 화면: #27
- 저장 데이터가 없는 브라우저의 첫 방문 전체 다운로드 시간, Edge·Firefox, 게임패드: #28
