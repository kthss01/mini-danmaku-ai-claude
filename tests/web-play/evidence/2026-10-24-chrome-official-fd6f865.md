# 웹 플레이 검증 기록 — 공식(새 checkout 빌드)

- 검증일: 2026-10-24 05:49~06:40 (KST)
- 검증자: Claude 세션 5 (모델 claude-opus-5-5, 노력치 high)
- 담당 이슈: #8 (부모 #2)
- 결과 요약: 세션 1~4 PR이 모두 머지된 최종 `main` `fd6f865`를 새 디렉터리에 clone해 문서 명령만으로 빌드·서빙했다(종료 코드 0, 238초). 실제 Chrome 155에서 로딩→시작→메뉴→스테이지 1 탄막 구간→조작, 설정 저장·진행 데이터 복원, 로더 누락 오류 화면을 확인했다. 누적 5분 탄막 플레이(약 307초, 스테이지 1 클리어 후 스테이지 2·3 진입)와 리플레이 저장·새로고침 후 재생은 같은 산출물로 Claude 데스크톱 앱 내장 Chromium에서 확인했다. **사람이 확인해야 하는 항목**(9절의 수동 확인 목록)은 미검증으로 남겼고, 최종 완료 판정은 보류한다.

## 1. 검증 대상 커밋

| 항목 | 값 |
| --- | --- |
| 메인 저장소 커밋 | `fd6f8659b945dcb7fcf1832f1e734585345477f0` (main) |
| `game/taisei` 커밋 | `f59212b72df3b68459b4677a6200e42be700078a` (fork PR kthss01/taisei#1 머지 커밋) |
| 포함된 PR | #9(7955e3a) #10(775df70) #11(03f580b) #12(1ad54ea) #13(89f3728) #15(fd9e00e) #16(6e77995) #17(3fbe736) #18(fd6f865) |
| checkout 방법 | `C:\Users\th_kim\Documents\github\mini-danmaku-ai-claude-qa`에 `git clone --recurse-submodules` 후 `scripts/setup-taisei.ps1` |
| 검증 종류 | **공식(새 checkout 빌드)** |

### 1-1. 작업 트리 상태

```text
git status --porcelain: 1개 항목
 M game/taisei
git submodule status --recursive:
 f59212b72df3b68459b4677a6200e42be700078a game/taisei (heads/master)
 380ef9389b38ec42506d5728dd05e94ac2f3c301 game/taisei/external/basis_universal (v1.12-488-g380ef93)
 7988b5e84c31616200ee2ffd2347386c6b3165a8 game/taisei/external/gamecontrollerdb (heads/master)
 5701d88c413508c75b5ac69faf1de7dc629e0f7d game/taisei/external/koishi (heads/master)
 8f5d88c270e4a46b152635dedad2eb4bc17a1dc2 game/taisei/external/openlibm (remotes/origin/taisei-v1.5)
```

` M game/taisei`는 줄바꿈 차이만 있는 1,129개 파일 때문이다. Git for Windows 기본값 `core.autocrlf=true`로 CRLF 체크아웃된 뒤 `setup-taisei.ps1`이 submodule에 `core.autocrlf=false`를 설정해 생긴다. 컨테이너 빌드는 커밋 기준으로 다시 clone해 컴파일하므로(`configs/web-build/container-build.sh:29-31`) 산출물에는 영향이 없다. 출처 기록에는 dirty로 남으므로 #4에 전달했다.

### 1-2. 산출물 출처 (provenance)

`tests/web-play/collect-env.ps1 -SiteDirectory build\web\site`를 QA clone에서 실행한 결과다.

| 항목 | 값 |
| --- | --- |
| 서빙 루트 경로 | `build\web\site` (QA clone) |
| 배치 형태 | 루트 셸 + `game/` 하위 (`site.entry` = `game/index.html`) |
| 생성 방법 | 이 기록에서 실행한 `.\scripts\build-web.ps1` (모드 BuildAndPackage) |
| 빌드 시각 | `2026-10-23T20:51:27Z` ~ `2026-10-23T20:55:09Z` UTC (`build-info.json`의 `build`) |
| 빌드 도구 | emsdk 5.0.3, `taiseiproject/linux-toolkit:20260804@sha256:1104b4a5…74b2` |
| build 미커밋 | 메인 ` M game/taisei`, Taisei 1,129개(줄바꿈만, 위 1-1) |
| manifest | `build-info.json` |
| 루트 `index.html` SHA-256 | `f0728725fe9680f3d19832f9693e6bb9a1a279d5c822cf5f58fbc10c68626b16` |
| `game/index.html` SHA-256 | `0a8b31f86be3f7b53cce0d3ae88d7d49ea5ac02e5c652597ab4d439596c08f2d` |
| `game/shell.js` SHA-256 | `aee98beb3689e41ba1bbe20ed10524034651b3271ad411a559403d908f8c8d57` |
| `game/shell.css` SHA-256 | `07d556327789e096057623e0d65ca1ff3588892cbebbd28b2a9294938eac5b7f` |
| `game/shell-config.js` SHA-256 | `55128ec63e5d7e780a0efbdb6056b84207d4721465332bd7657d8e516742dc7b` |
| `game/taisei.html` SHA-256 | `113240a898a555b79b8dcfa49c75fe5aa89a68831c377431347e8127ca3ac555` |
| `game/taisei.js` SHA-256 | `d49ca968c16d0a69cc275f21a2f537db51c151a25401781c911149c328c73a01` (101,107 bytes, 세션 1 기록과 같음) |
| `game/taisei.wasm` SHA-256 | `f0cfaa626e723a1dff9cdb88fff2d404ebb53b84df795e2a19dee9b055a20c99` (4,539,198 bytes. 크기는 세션 1 기록과 같고 해시는 다름 — 세션 1이 기록한 "바이트 단위 재현성 미보장") |
| `COPYING.txt` SHA-256 | `507ba6eaceaf6fd923246480f53932b25a1ebbb25b2dd19c4f37bfc5fc83795a` (루트·`game/` 동일) |
| `data/` | 529개, 207.1 MB |
| `site/` | 549개 파일, 222,408,181 바이트 (`build-info.json` 제외) |

## 2. 환경

| 항목 | 값 |
| --- | --- |
| OS | Microsoft Windows 11 Home 10.0.26200 |
| CPU | AMD Ryzen 7 7840HS |
| GPU | AMD Radeon 780M (Chrome WebGL 렌더러 `ANGLE (AMD, AMD Radeon(TM) 780M Direct3D11 vs_5_0 ps_5_0, D3D11)`), NVIDIA GeForce RTX 4060 Laptop GPU |
| 해상도·배율 | 1646×1029 주 화면, DPR 1.75 |
| 브라우저 1 (필수) | **Google Chrome 155.0.8059.86** (사용자 프로필, Claude in Chrome으로 조작). 창 1646×981, 캔버스 CSS 1646×804 → 버퍼 2881×1407 |
| 브라우저 2 (보조) | Claude 데스크톱 앱 내장 Chromium 152.0.7977.167. 뷰포트 1024×768 에뮬레이션, 캔버스 버퍼 1792×1344, 화면 주사율 120Hz |
| Docker / 빌드 이미지 | Docker 26.1.1, 위 이미지 |
| Git / Python | Git 2.44.0.windows.1, Python 3.12.2 |

## 3. 실행 명령과 결과

```text
git clone --recurse-submodules https://github.com/kthss01/mini-danmaku-ai-claude.git mini-danmaku-ai-claude-qa
→ 종료 코드 0. HEAD fd6f865, game/taisei f59212b7
.\scripts\setup-taisei.ps1
→ 종료 코드 0
.\scripts\build-web.ps1
→ 종료 코드 0, 238초(emsdk named volume 캐시 사용), build/web/site 생성
```

```text
python scripts/serve-web.py
→ serve-web: 루트 …\mini-danmaku-ai-claude-qa\build\web\site
  serve-web: 격리 헤더(COOP/COEP) 꺼짐
  serve-web: http://127.0.0.1:8080/ 에서 제공 중 (종료: Ctrl+C)
  LISTEN 주소 127.0.0.1:8080
```

```text
python -I scripts/check-web-assets.py --root build/web/site --url http://127.0.0.1:8080 --entry <진입> --require-wasm --verify-hashes --sample-data -1
→ index.html:        HTTP 543건 실패 0, 오류 0, 경고 0
→ game/index.html:   HTTP 542건 실패 0, 오류 0, 경고 0
→ game/taisei.html:  HTTP 539건 실패 0, 오류 0, 경고 0
```

접속 URL: `http://127.0.0.1:8080/` (로컬 전용, `game/index.html`로 이동)

## 4. QA 항목별 결과

| ID | 상태 | 증거 (관찰 내용) | 결함 이슈 |
| --- | --- | --- | --- |
| QA-01 | 성공 | 위 3절. 문서 명령만으로 새 clone에서 빌드·패키징 성공, 파일 목록·용량·버전·해시 기록. 출처에 줄바꿈 dirty가 남는 문제는 산출물 영향 없음으로 확인 | #4 (출처 기록) |
| QA-02 | 성공 | 빌드 후 `git status --porcelain`에 `build/` 산출물 없음(` M game/taisei`만, 1-1 참조) | |
| QA-03 | 미검증 | 확인: 기본 명령으로 `127.0.0.1:8080` 바인딩, 안내 URL 출력, index 제공. 사용한 임시 서버는 프로세스 종료 후 포트 해제 확인. 남음: 터미널에서 Ctrl+C로 종료하는 문서 절차는 자동화 도구로 실행하지 못함 | |
| QA-04 | 성공 | `.wasm` → `application/wasm`, 없는 경로 404, 세 진입점 해시 검사 통과. 서버 로그 2,515건 중 4xx는 검사용 의도 요청과 텍스트 페이지의 `/favicon.ico` 3건뿐 | |
| QA-05 | 성공 | 루트 없음: 종료 코드 2와 안내. 사용 중 포트(`python -m http.server 8098` 선점): 종료 코드 3, `WinError 10048` 안내, LISTEN 1개 유지. 탐색 3차에서 실패로 기록한 Windows 중복 바인딩이 PR #18로 수정됐음을 재검증 | #7 (수정됨) |
| QA-10 | 성공 | Chrome, 빈 IndexedDB: 루트 → `game/index.html` `ready`(시작 버튼 대기) → 클릭 3초 뒤 `playing`, "리소스를 미리 내려받는 중 248 / 1016" 진행 표시 | |
| QA-11 | 성공 | 시작 전 `navigator.userActivation.hasBeenActive=false`, 로더 미로드. 시작 버튼 클릭 후에만 로더 로드 | |
| QA-12 | 성공 | 공식 셸 파일만 있고 `taisei.js`가 없는 사본에서 시작 → `error` 상태, "게임 로더(taisei.js)를 불러오지 못했습니다" 원인·다시 시도 버튼(내장 Chromium) | |
| QA-13 | 성공 | 셸 조작 안내(방향키·Z·X·C·Shift·Ctrl·Esc·M)가 `src/config.h` 기본 키와 일치 | |
| QA-14 | 성공 | 루트·`game/`의 `COPYING.txt`(동일 해시)에 MIT 고지와 "original soundtrack … CC-BY 4.0", 캐릭터 초상화 고지 포함. 게임 셸 하단 "라이선스 고지" 링크(`game/COPYING.txt`) | |
| QA-15 | 성공 | 모의 방식: 공식 셸 사본의 `<head>` 맨 앞에 `getContext('webgl2')`가 `null`을 돌려주게 하는 스크립트를 넣어 내장 Chromium에서 접속 → `data-state=unsupported`, "WebGL 2 컨텍스트를 만들 수 없습니다 … 최신 Chrome 또는 Edge에서 다시 열어주세요" 표시, 시작 버튼 숨김. 실제로 WebGL을 끈 브라우저(플래그·설정)로는 실행하지 않음 | |
| QA-20 | 성공 | Chrome: 첫 프레임 후 `document.activeElement.id === 'canvas'` | |
| QA-21 | 성공 | Chrome, 게임 활성(`playing`) 중 실제 키 입력 ↓×5·Space×3·PageDown×2 → `scrollY` 0 유지, scroll 이벤트 0건, 포커스 canvas 유지. 문서 높이 = 창 높이(804), `body overflow:hidden` | |
| QA-22 | 미검증 | 실제 키를 누른 채 다른 창으로 전환하는 동작은 자동화로 재현할 수 없음 → 사용자 확인 필요 | |
| QA-23 | 미검증 | 같은 이유 | |
| QA-30 | 성공 | 메인 메뉴 이동·선택(Options, Replays, Start Story), 난이도·캐릭터 선택, 일시정지 메뉴 이동·선택, 옵션 X(뒤로) | |
| QA-31 | 성공 | Chrome·내장 Chromium 모두 스테이지 1 탄막 구간 진입. 내장 Chromium에서 스테이지 1 클리어("Stage Clear!") 후 스테이지 2·3 진입 | |
| QA-32 | 성공 | 내장 Chromium, 같은 공식 산출물: ↑ 0.7초 유지 → 화면 아래쪽에서 위쪽으로 이동, ↓ 0.7초 → 아래로 복귀, ← 0.4초 → 약 40px 이동, → 이동. Chrome에서는 좌우 자동 입력으로 이동 확인 | |
| QA-33 | 성공 | Z 유지로 샷 발사, 적 격파, 점수 증가(Chrome 41,973 → 60,137) | |
| QA-34 | 미검증 | 확인(내장 Chromium): 같은 0.4초 입력에서 일반 이동 약 40px, Shift 유지 이동 약 8px로 속도 감소. Shift 유지 시 음양옥이 저속 전용 배치로 바뀜. 남음: 피격 판정 표시는 축소 화면에서 판독이 확실하지 않음(탐색 1차, 이전 산출물에서는 관찰) | |
| QA-35 | 미검증 | 확인(내장 Chromium): X → 스펠 "Fantasy Seal -Burst-" 발동, HUD Spell Cards 별 3개 → 2개. 남음: 이펙트에 가려 탄 소거를 판독하지 못함 | |
| QA-36 | 성공 | 내장 Chromium: Esc → "Game Paused"(Options/Return to Game/Restart the Game/Stop the Game) → Z(Return to Game) → 진행 중이던 봄 이펙트와 함께 게임 재개. "Stop the Game"으로 메뉴 나가기(리플레이 저장 화면)도 확인 | |
| QA-37 | 미검증 | 오디오 드라이버 초기화와 BGM 이름 표시는 탐색에서 확인. 실제 소리 청취는 사람이 확인해야 함 | |
| QA-38 | 성공 | 내장 Chromium에서 탄막 구간 누적 약 307초(아래 5절). Chrome에서 같은 측정은 미수행(6절) | |
| QA-39 | 미검증 | 측정한 것은 rAF 콜백/초뿐이다(내장 Chromium 평균 120.1, 최소 32). 이것은 브라우저 콜백 빈도이며 게임 HUD·논리 FPS가 아니다. 공식 실행에서 HUD FPS 숫자는 좁은 패널 때문에 판독하지 못했다. Chrome에서는 창이 가려졌을 때 rAF가 1~2/초로 떨어져 측정 불가(6절) → 사용자 확인 필요 | |
| QA-40 | 성공 | Chrome: Options → SFX 50% → 40% → X로 나가고 "Saved persistent storage to IndexedDB" 로그 확인 → 새로고침 → 40% 유지. 저장 로그 전에 새로고침한 첫 시도는 50%로 돌아감(메뉴를 나갈 때 저장하는 설계, 세션 2 RUNTIME.md 2.3) | |
| QA-41 | 성공 | 내장 Chromium: Stop the Game → Save Replay Yes → `replay_save: Saving /persistent/storage/replays/taisei_20261024_06-32-16-508_stg1_reimuA_easy.tsr` → 새로고침 → Replays 목록 `2026-10-24 06:32 Player ReimuA Easy Stage 1` → 재생 | |
| QA-42 | 성공 | Chrome: 새로고침 후 인트로 없이 메인 메뉴(진행 데이터 복원). 내장 Chromium: 스테이지 클리어 후 Stage Practice·Spell Practice 해금 유지 | |
| QA-43 | 성공 | 게임오버 → Continue로 재진입 반복(Chrome 2회, 내장 Chromium 6회 이상), 오류·멈춤 없음 | |
| QA-44 | 성공 | Chrome에서 새로고침 4회 후 매번 `playing`, 셸 오류 0 | |
| QA-50 | 성공 | README 빠른 시작(웹)의 clone·setup·build-web·serve-web 명령과 URL `http://127.0.0.1:8080/`이 공식 기록 3절에서 실행한 명령·출력과 같음 | |
| QA-51 | 성공 | WEB_SETUP의 버전(이미지 digest·emsdk 5.0.3·Taisei f59212b7)·명령·URL·검증 범위·제약을 공식 기록과 대조해 일치. Python 최소 버전은 확인하지 않았다고 명시 | |
| QA-52 | 성공 | BUILD(`build/web/site`, `game/` 하위, 진입 `game/index.html`)·SHELL(루트 → `game/index.html`)·SERVING(기본 루트 `build/web/site`, 8080, COOP/COEP 불필요)·RUNTIME(pthreads 미사용, `data/` 문서 기준 상대 경로)이 서로 모순되지 않음 | |

공통: Chrome·내장 Chromium 모두 셸 `errors`·`downloadErrors` 0건, 페이지 오류 0건. 콘솔 경고 `FS.syncfs operations in flight`(#5에 전달됨)는 그대로 발생.

## 5. 플레이 로그 (QA-38, 누적 5분)

내장 Chromium, 2026-10-24 06:24:02~06:34:05 KST. 자동 입력(공격 유지, 0.4초마다 좌우 이동, 약 6초마다 봄)으로 10~20초 구간을 돌리고, 구간이 끝날 때마다 화면을 확인했다. 게임오버·대사·클리어 화면이 낀 구간은 **전부 제외**하고 탄막 구간만 합산했다.

| 구간 | 길이 | 판정 | 비고 |
| --- | --- | --- | --- |
| s1, s2 | 40초 | 포함 | 스테이지 1 도중 |
| s3 | 20초 | 제외 | 끝에 게임오버 |
| s4~s6 | 30초 | 포함 | Continue 후 |
| s7~s9 | 30초 | 제외 | 보스 대사 |
| s10~s14 | 50초 | 포함 | 스테이지 1 보스전 |
| s15 | 15초 | 제외 | Stage Clear 화면 |
| s16 | 15초 | 포함 | 스테이지 2 |
| s17 | 15초 | 제외 | 게임오버 |
| s18 | 13초 | 포함 | Continue 직후 약 2초 제외 |
| s19, s20 | 30초 | 포함 | |
| s21 | 15초 | 제외 | 게임오버 |
| s22 | 13초 | 포함 | Continue 직후 제외 |
| s23~s26 | 60초 | 제외 | 스테이지 2 보스 대사(Z 유지로 대사가 넘어가지 않음) |
| s27, s28 | 30초 | 포함 | 스테이지 2 보스전 |
| s29 | 15초 | 제외 | 게임오버 |
| s30 | 13초 | 포함 | Continue 직후 제외 |
| s31~s34 | 60초 | 포함 | 스테이지 2~3 |
| s35 | 15초 | 제외 | 게임오버 |
| s36 | 13초 | 포함 | Continue 직후 제외 |
| s37 | 15초 | 제외 | 대사 |

- 누적 탄막 플레이 시간(포함 구간 합): **약 307초**
- 콘솔·셸 오류: 0건. 네트워크 실패: 0건(서버 로그 기준)

## 6. FPS 측정 (QA-39)

- 측정 방법: 페이지에서 `requestAnimationFrame` 콜백 수를 1초마다 집계했다(**rAF 콜백/초**). 이 값은 브라우저가 화면 갱신 콜백을 부른 빈도이며, 게임이 실제로 그린 프레임 수나 논리 프레임 속도(HUD 우하단 FPS)를 입증하지 않는다. 공식 실행에서는 HUD FPS 숫자를 판독하지 못했다(탐색 1·2차, 이전 산출물에서는 HUD 59.10~61.26 관찰).
- 내장 Chromium(120Hz 화면, 버퍼 1792×1344): 탄막 구간 477초 표본, rAF 콜백/초 **평균 120.1, 최소 32**(1초, 스테이지 전환 시점). 100 미만은 1회.
- Chrome(버퍼 2881×1407): 활성 플레이 15초 동안 rAF 콜백/초 34~61(대부분 60). 다른 구간에서는 1~2까지 떨어졌다. 같은 창의 게임 없는 텍스트 페이지도 1~5였고, 메인 스레드 긴 작업은 0건이었다. 이 대조 관측으로 **Chrome 창이 다른 창에 가려졌을 때 브라우저가 갱신을 줄인 환경 요인으로 추정**한다. 이 PC·이 조작 방식에서 관찰한 결과이며 다른 환경의 원인으로 확정하지 않는다. 이 상태에서는 게임 시간도 느려졌다.
- 결론: Chrome 창을 앞에 둔 상태의 HUD FPS는 **미검증**. 사용자 확인 필요.

## 7. 결함과 미해결 사항

| 번호 | 증상 | 재현 절차 | 담당 세션 이슈 | 상태 |
| --- | --- | --- | --- | --- |
| 1 | 새 clone + setup 직후 `game/taisei` 1,129개 파일이 줄바꿈 차이로 dirty, 빌드 출처에 미커밋으로 기록 | 1-1 절차 | #4 | 전달함. 산출물 영향 없음 |
| 2 | Windows 포트 충돌 미감지 | 탐색 3차 | #7 | PR #18로 수정, 이번 기록에서 재검증 성공 |
| 3 | `FS.syncfs operations in flight` 경고 반복 | 저장 시점 | #5 | 전달함, 데이터 손상 미관찰 |
| 4 | 스테이지 도중·옵션 메뉴 안에서 새로고침하면 그 사이 변경이 저장되지 않음 | QA-40 첫 시도 | #5 | 설계상 제약(저장은 메뉴를 나가거나 스테이지가 끝날 때). 문서에 제약으로 기재 |

## 8. 완료 차단 판정

- 검증 범위에서 신규 플레이 차단 결함은 관찰하지 못했다. **최종 완료 판정은 보류**한다.
- #2 완료 조건별 판정과 미검증 항목의 분류는 [docs/web/QA.md](../../../docs/web/QA.md)의 "완료 판정" 표가 기준이다. 남은 필수 항목은 모두 사람 확인 항목이다.
- 출처 기록 dirty(#4)는 이 기록 당시 상태 그대로 보존한다. 수정 PR #25 머지 후 깨끗한 checkout의 setup·작업 트리·provenance만 표적 재검증해 별도 기록으로 추가한다(게임 코드·빌드 입력이 같으면 5분 QA는 반복하지 않는다).

## 9. 사람 수동 확인 목록

한 번에 끝나는 절차다. 결과를 항목 번호와 함께 알려 주면 이 기록에 반영한다.

1. QA clone에서 `python scripts/serve-web.py` 실행 → Chrome 창을 화면 앞에 두고 `http://127.0.0.1:8080/` → "게임 시작" → 화면 한 번 클릭
2. **소리(QA-37, 필수)**: 메뉴·스테이지에서 BGM과 공격·피격 효과음이 들리는가
3. **FPS(QA-39, 필수)**: 스테이지 1 탄막 구간 30초 동안 화면 오른쪽 아래 HUD FPS 최저·평균
4. **저속(QA-34, 필수)**: `Shift`를 누르고 있을 때 캐릭터 중앙에 피격 판정 표시가 보이는가
5. **봄(QA-35, 필수)**: 탄이 많을 때 `X` → 주변 탄이 사라지는가
6. **창 전환(QA-22·23, 필수)**: 방향키를 누른 채 `Alt+Tab`으로 다른 창 → 2초 뒤 복귀. 캐릭터가 계속 움직이지 않는가, 일시정지 메뉴가 뜨거나 정상 재개되는가, 오류가 없는가
7. **전체 화면(#6 전달, 비차단)**: 게임 화면 오른쪽 위 "전체 화면" 버튼 또는 `F11` → 전체 화면 전환·`Esc` 해제
8. **서버 종료(QA-03, 필수)**: 서버 터미널에서 `Ctrl+C` → "종료합니다." 출력 후 프롬프트 복귀
