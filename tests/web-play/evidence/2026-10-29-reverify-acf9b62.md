# 웹 플레이 검증 기록 — #25 표적 재검증·QA-03 (새 checkout 빌드)

- 검증일: 2026-10-29 10:54~13:20 (UTC)
- 검증자:
  - clone·setup: Claude "웹 #25 표적 재검증" 세션(claude-sonnet-5-5 / high), 10:54 UTC
  - 빌드·출처 확인·QA-03: Claude "이슈 정리 및 병렬 작업" 세션(claude-opus-5-5 / max), 13:12~13:20 UTC
- 담당 이슈: #8 (부모 #2). 관련: #4(출처 dirty), PR #25(수정), #27(사람 확인)
- 결과 요약
  - PR #25 머지 커밋 `acf9b62`를 새 디렉터리에 clone하고 문서 명령으로 setup·빌드했다.
  - setup 직후와 빌드 후 모두 `git status --porcelain`이 비어 있다. `build-info.json`의 미커밋 목록 4개도 모두 `[]`다. [2026-10-24 공식 기록](2026-10-24-chrome-official-fd6f865.md) 1-1의 출처 dirty(#4)가 해소됐다.
  - 같은 산출물로 QA-03(서버 실행 → `Ctrl+C` 종료 → 포트 해제)을 확인했다.
  - 공식 기록 8절에 따라 게임 코드와 셸이 같으므로 5분 플레이 QA는 반복하지 않았다. Taisei 커밋과 셸·로더 해시가 공식 기록과 같다.

## 1. 검증 대상

| 항목 | 값 |
| --- | --- |
| 메인 저장소 커밋 | `acf9b6253f35884888a0a1928d8afc1c3a98970c` (main, PR #25 머지 커밋) |
| `game/taisei` 커밋 | `f59212b72df3b68459b4677a6200e42be700078a` (공식 기록과 같음) |
| checkout 방법 | `C:\Users\th_kim\Documents\github\mini-danmaku-ai-claude-qa2`에 `git clone --recurse-submodules`(10:54 UTC) 후 `scripts/setup-taisei.ps1` |
| 검증 종류 | **공식(새 checkout 빌드)**, #4 표적 재검증 |

### 1-1. 줄바꿈 조건과 setup 결과

| 항목 | 값 |
| --- | --- |
| Git | 2.44.0.windows.1. `core.autocrlf`는 system `true`이고 global에는 설정이 없다. 공식 기록 1-1에서 dirty가 생긴 것과 같은 CRLF 체크아웃 조건이다 |
| setup 출력 | CRLF 추적 파일 1,754개를 LF로 다시 썼고 종료 코드는 0이다(재검증 세션 보고) |
| setup 직후 | `git status --porcelain` 빈 값(재검증 세션 보고) |
| 빌드 후 직접 확인(13:18 UTC) | 메인 `git status --porcelain` 빈 값, `git -C game/taisei status --porcelain` 0줄, `game/taisei`의 `core.autocrlf=false`. 공식 기록 1-1의 예시 파일 `resources/00-taisei.pkgdir/gfx/stage4/mansion.material`은 CRLF 0줄 |

```text
git submodule status --recursive:
 f59212b72df3b68459b4677a6200e42be700078a game/taisei (heads/master)
 380ef9389b38ec42506d5728dd05e94ac2f3c301 game/taisei/external/basis_universal (v1.12-488-g380ef93)
 7988b5e84c31616200ee2ffd2347386c6b3165a8 game/taisei/external/gamecontrollerdb (heads/master)
 5701d88c413508c75b5ac69faf1de7dc629e0f7d game/taisei/external/koishi (heads/master)
 8f5d88c270e4a46b152635dedad2eb4bc17a1dc2 game/taisei/external/openlibm (remotes/origin/taisei-v1.5)
```

## 2. 빌드와 산출물 출처

- 명령: `.\scripts\build-web.ps1`(모드 BuildAndPackage). Docker Desktop 4.30.0, 엔진 26.1.1.
- 실행: 13:12:40~13:17:24 UTC, 285초, 종료 코드 0.
- 경위: 재검증 세션의 첫 빌드는 Docker 엔진이 응답하지 않아(`docker version` 시간 초과) 끝나지 않았다. Docker Desktop을 재시작한 뒤 같은 clone에서 다시 실행했다. 첫 시도의 산출물은 남지 않았다(`build/web` 없음).

`build/web/site/build-info.json`:

| 항목 | 값 | 공식 기록(2026-10-24) |
| --- | --- | --- |
| 빌드 시각 | `2026-10-29T13:12:45Z` ~ `13:17:12Z`, 패키징 `13:17:18Z` | |
| 빌드 도구 | Emscripten 5.0.3, `taiseiproject/linux-toolkit:20260804@sha256:1104b4a5…74b2` | 같음 |
| `build.repositoryCommit`, `packaging.repositoryCommit` | `acf9b62…` | `fd6f865…` |
| `build.taiseiCommit` | `f59212b7…` | 같음 |
| `build.repositoryDirtyEntries` | `[]` | `[" M game/taisei"]` |
| `build.taiseiWorktreeDirtyEntries` | `[]` | 1,129개(줄바꿈만) |
| `packaging.repositoryDirtyEntries` | `[]` | |
| `packaging.webShellDirtyEntries` | `[]` | |
| data | 529개, 217,186,447 바이트(207.1 MiB), content-addressed | 같음 |
| site | 549개 파일, 222,408,181 바이트(`build-info.json` 제외), 진입 `game/index.html` | 같음 |
| 셸·로더 SHA-256 | 루트 `index.html`, `game/index.html`, `shell.js`, `shell.css`, `shell-config.js`, `taisei.html`, `taisei.js`, `COPYING.txt` | 모두 같음 |
| `game/taisei.wasm` | 4,539,198 바이트, `cee2e9dfa115d8f23ed1ac64896a0221dbbd2bee6d60b2657ddad8b97e9cad4e` | 크기 같고 해시 다름 |

- `taisei.wasm`의 해시 차이는 세션 1이 기록한 "바이트 단위 재현성 미보장"과 같은 현상이다. 공식 기록에서도 세션 1 빌드와 해시가 달랐다.
- 빌드 후 `git status --porcelain`이 비어 있어 QA-02도 그대로 성립한다.

## 3. QA-03 서버 실행·종료

- 명령: 문서 명령에 포트만 바꿔 `python scripts/serve-web.py --port 8097`로 실행했다. 실행 위치를 지정할 수 없어 qa2의 스크립트를 절대 경로로 불렀다. 기본 루트는 스크립트 위치로 정해진다.
- 포트를 바꾼 이유: 8080은 2026-10-24 06:03(KST)에 시작된 다른 `serve-web.py`(PID 39700)가 쓰고 있었다. 공식 QA 때 띄운 서버로 보이며 건드리지 않았다.

```text
serve-web: 루트 C:\Users\th_kim\Documents\github\mini-danmaku-ai-claude-qa2\build\web\site
serve-web: 격리 헤더(COOP/COEP) 꺼짐
serve-web: http://127.0.0.1:8097/ 에서 제공 중 (종료: Ctrl+C)
```

- 실행 중(13:19:41 UTC): `127.0.0.1:8097` LISTEN 1개(PID 24188).

  | 요청 | 응답 |
  | --- | --- |
  | `/` | 200 `text/html` |
  | `/game/index.html` | 200 `text/html` |
  | `/game/taisei.wasm` | 200 `application/wasm`, 4,539,198 B |
  | `/nope` | 404 |

- 종료: Claude 데스크톱 앱의 터미널 패널 탭에 `Ctrl+C`를 보냈다. 사람이 누른 키가 아니라 도구가 보낸 입력이다. 서버가 `serve-web: 종료합니다.`를 출력했고 PowerShell 프롬프트로 돌아왔다.
- 종료 후(13:19:50 UTC): `:8097` LISTEN 없음(앞선 요청의 TIME_WAIT만 남음), PID 24188 없음. 포트가 해제됐다.
- 판정: **성공**. 공식 기록 4절에서 남았던 "터미널에서 Ctrl+C로 종료하는 문서 절차"를 실행했다.

## 4. 공개 주소 확인의 보조 관찰 (#29)

[PAGES.md](../../../docs/web/PAGES.md) "검증 결과"에 기록한 내용이다.
- 대상: 공개 배포(main `0387c04`를 CI가 새 checkout으로 빌드, Taisei `f59212b7`).
- 환경: Claude 데스크톱 앱 내장 Chromium 152. 키를 누른 채 유지하는 조작은 DOM 키 이벤트로 했다.

Chrome에서 사람이 확인한 결과가 아니므로 아래 항목의 상태는 바꾸지 않는다.

| ID | 관찰 | 남은 것 |
| --- | --- | --- |
| QA-34 | Shift를 누르는 동안 캐릭터 둘레에 원형 표시가 나타남 | 중앙 판정 점은 판별하지 않음 |
| QA-35 | X → 스펠 카드 발동, Spell Cards 3 → 2 | 탄 소거는 판독하지 않음 |
| QA-39 | 패널이 앞에 있을 때 HUD FPS 59.88~60.03 | Chrome HUD FPS |

## 5. 사람 확인(#27) 처리

- 2026-10-29: 사용자(저장소 소유자)가 "현재 작업 진행 상황 확인" 세션에서 #27 사람 확인을 "생략하고 진행"하기로 정했다.
- 같은 날 13:00 UTC 무렵: 사용자가 이 세션에 직접 플레이해 보니 잘 된다고 알렸다. 사용한 브라우저·주소와 항목별 관찰(소리, FPS 숫자 등)은 받지 않았다. 그래서 항목 상태를 `성공`으로 올리지 않는다.

| 항목 | 처리 |
| --- | --- |
| QA-03 서버 종료 | 3절에서 **성공** |
| QA-37 소리 | 사용자 결정으로 생략 |
| QA-39 Chrome HUD FPS | 사용자 결정으로 생략(보조: 4절) |
| QA-34 피격 판정 표시 | 사용자 결정으로 생략(보조: 4절) |
| QA-35 봄 탄 소거 | 사용자 결정으로 생략(보조: 4절) |
| QA-22·23 창 전환 키 해제·탭 복귀 | 사용자 결정으로 생략 |
| 전체 화면(비차단) | 사용자 결정으로 생략 |

생략한 항목은 상태를 `미검증`으로 둔 채 #28로 넘긴다.

## 6. 조건별 판정

조건별 판정표와 생략 결정의 예외 규칙은 [docs/web/QA.md](../../../docs/web/QA.md)의 "완료 판정 기준"에 반영했다.

| #2 조건 | 엄격 기준(QA.md 판정 규칙) | 사용자 결정 반영 |
| --- | --- | --- |
| 1. 새 checkout 빌드·HTTP 실행 재현 | 충족(QA-01~05 성공) | 충족 |
| 2. 탄막 조작·소리 | 보류(QA-34·35·37 미검증) | 충족(사용자 결정) |
| 3. 로컬 URL·실행 절차 | 충족(QA-03·50·51 성공) | 충족 |
| 4. 플레이 차단 문제 해결·증거 | 보류(QA-22·23·39 미검증). 결함 #4 출처 dirty는 해소 | 충족(사용자 결정) |
| 5. PR·이슈 기록 | 충족(세션 1~5 PR #9~#18·#25와 이 후속 증거 PR) | 충족 |
| 6. 빌드·제목 화면만으로 완료 금지 | 충족 | 충족 |
