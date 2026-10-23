# 웹 플레이 검증 기록 — 탐색 3차(세션 3 셸 + 기존 산출물, 세션 1 계약 배치)

- 검증일: 2026-10-23 21:15~21:30 (KST)
- 검증자: Claude 세션 5 (모델 claude-opus-5-5, 노력치 high — 사용자가 이 세션 모델을 변경)
- 담당 이슈: #8 (부모 #2)
- 결과 요약: `main` `1ad54ea`(PR #12 세션 3 셸 머지)의 `web/`를 세션 1 계약 배치(루트 `index.html` + `game/`)로 기존 게임 산출물과 결합해 탐색했다. 루트 → `game/index.html` 이동, 시작 버튼 대기(`ready`), 클릭 후 `loading` → `playing`, 캔버스 포커스, 스테이지 1 탄막 구간, 스크롤 방지, 로더 누락 시 오류 화면이 동작했다. 포트 충돌 미감지 결함 1건을 #7에 전달했다. **공식 판정 아님**(세션 1 빌드 산출물 아님, manifest 없음). 공식 상태는 전부 `미검증` 유지.

## 1. 검증 대상 커밋

| 항목 | 값 |
| --- | --- |
| 메인 저장소 커밋 | 셸 `web/`·서버·검사 도구: `origin/main` `1ad54ea` (PR #10 775df70, PR #12 1ad54ea 포함) |
| `game/taisei` 커밋 | 산출물 출처 gitlink `5668c41b` (세션 5 clone은 submodule 미초기화) |
| 포함된 PR | #10, #12 머지. #11(세션 1, head 1d56f44)·#13(세션 2, head 811a8ce) 미머지 |
| 검증 종류 | **탐색(기존 산출물 + 머지된 셸)** |

### 1-2. 산출물 출처

| 항목 | 값 |
| --- | --- |
| 서빙 루트 | `build/explore-site` (Git 제외). `git archive origin/main web`의 파일을 루트로, `web/game/*`를 `game/`으로, 기존 산출물(`build/explore-taisei-web`)의 `taisei.*`·`data/`·정적 파일을 `game/`으로 수동 복사 |
| 배치 형태 | 루트 셸 + `game/` 하위(세션 1 계약과 같은 구조, 세션 1 패키징 스크립트로 만든 것은 아님) |
| 게임 산출물 | 1차 기록과 동일(`taisei.wasm` SHA-256 `eb97b68b…`). **출처 미확인** |
| manifest | 없음 |

## 2. 환경

Windows 11 10.0.26200, Claude 데스크톱 앱 내장 Chromium(뷰포트 1024×768, DPR 1.75), Python 3.12.2. 서버 `127.0.0.1:8096`(새 오리진, IndexedDB 비어 있는 상태에서 시작). 사용자 Chrome/Edge 미사용.

## 3. 실행 명령과 결과

```text
python -I <scratchpad>/s4/serve-web.py --root build/explore-site --port 8096      # main 775df70 사본
python -I <scratchpad>/s4/check-web-assets.py --root build/explore-site --url http://127.0.0.1:8096 --entry game/index.html --sample-data 10
→ 통과(오류 0, 경고 1). 경고 no-wasm: 셸이 taisei.js를 동적으로 불러와 정적 추적이 .wasm에 도달하지 못함(Codex가 #7에 이미 지시한 항목)
```

처음에는 포트 8091로 실행했으나 다른 세션의 mock 서버가 이미 8091을 쓰고 있었고, serve-web.py가 충돌을 감지하지 못한 채 "제공 중"을 출력했다(결함 1). 빈 포트 8096으로 다시 실행했다.

접속 URL: `http://127.0.0.1:8096/` (로컬 전용, 루트 → `game/index.html`로 이동)

## 4. QA 항목별 결과 (탐색)

| ID | 상태 | 증거 (관찰 내용) | 결함 이슈 |
| --- | --- | --- | --- |
| QA-05 | 실패 | 사용 중 포트로 실행 시 종료 코드 3이 아니라 정상 실행처럼 동작(Windows). 산출물 없는 디렉터리 경우는 미실행 | #7 |
| QA-10 | 성공 | 루트 접속 → `game/index.html`, `data-state=ready`(시작 버튼 대기). 클릭 후 "리소스를 미리 내려받는 중 0 / 1016" 진행 표시 → 게임 화면 | |
| QA-11 | 성공 | 시작 전 `navigator.userActivation.hasBeenActive=false`, `taisei.js` 미로드. 시작 버튼 클릭 후에만 로더를 불러옴 | |
| QA-12 | 성공 | `taisei.js`가 없는 사본(`/broken/game/index.html`)에서 시작 → `data-state=error`, "게임 로더(taisei.js)를 불러오지 못했습니다" 원인·다시 시도 버튼 표시. 무한 스피너 없음 | |
| QA-13 | 성공 | 셸 조작 안내(이동·Z·X·C·Shift·Ctrl 대화 건너뛰기·Esc·M)가 소스 기본 키와 일치 | |
| QA-20 | 성공 | 첫 프레임 이후 `document.activeElement.id === 'canvas'` | |
| QA-21 | 성공 | 스테이지 중 ↓·Space 입력 후 `scrollX=0, scrollY=0`, `scrollHeight == innerHeight` | |
| QA-31 | 성공 | 셸 경유로 Start Story → Easy → Reimu → 스테이지 1 탄막 구간 진입 | |
| QA-38 | 미검증 | 이번 기록 플레이 약 1분. 누적(1~3차) 약 5분이지만 구간이 짧고 대부분 게임오버로 끊겨 공식 증거로 쓰지 않음 | |
| QA-44 | 미검증 | 확인: 셸 경유 재접속(새로고침 후 시작 버튼 → 게임)을 3회 정상 수행. 남음: 플레이 중 F5 후 콘솔 오류 확인, 재접속 시 네트워크 요청이 캐시로 대체되는지 확인 | |

네트워크: `performance` 리소스 기록 250건(브라우저 기본 버퍼 한도, `data/` 244건) 중 4xx/5xx 0건. 전체 1,016건 프리페치 중 일부만 집계됨.
콘솔: 오류 0건. 경고 `FS.syncfs operations in flight` 반복(#5에 전달됨).

## 5. 관찰했으나 재현되지 않은 현상

- **게임 화면 확대(잘림)**: 첫 시작 1회에서 게임 화면이 왼쪽 위 약 1/1.75 영역만 확대되어 보였다(컷신 문장·메인 메뉴 오른쪽이 잘림). 캔버스 CSS 1024×768, 버퍼 1792×1344(DPR 1.75)로 크기 값은 정상이었다. 같은 조건의 업스트림 `game/taisei.html`은 정상 표시. 이후 뷰포트 900×700 에뮬레이션, 기본 크기 복귀, IndexedDB 삭제 후 최초 실행까지 3회 다시 시작했으나 **재현되지 않음**. 첫 시도 때 브라우저 패널이 숨김 상태였던 점이 원인일 가능성이 있다. 결함으로 등록하지 않고, 실브라우저 공식 QA에서 다시 확인한다. 셸은 첫 프레임 시점에도 `syncCanvasSize()`로 `canvas.width/height`를 CSS 크기로 덮어쓴다(`web/game/shell.js` 329행, 업스트림 셸은 resize 때만) — 재현되면 우선 확인할 지점.

## 6. 결함

| 번호 | 증상 | 재현 절차 | 담당 세션 이슈 | 상태 |
| --- | --- | --- | --- | --- |
| 1 | Windows에서 포트 충돌 미감지. 두 프로세스가 같은 포트를 LISTEN, 요청은 먼저 뜬 서버로 감 | `python -m http.server 8097 --bind 127.0.0.1` 후 `serve-web.py --port 8097` | #7 | 전달함(이슈 #7 댓글). `http.server`의 `allow_reuse_address`가 Windows `SO_REUSEADDR`로 중복 바인딩을 허용하는 것으로 추정 |

## 7. 완료 차단 판정

- 탐색에서 새로 관찰한 플레이 차단 결함: 없음. 포트 충돌 미감지는 QA 실패 항목(QA-05)이지만 빈 포트에서는 플레이를 막지 않음. **최종 차단 판정 미완료**
- 사용자 확인 필요(자동화 불가): 실제 소리 청취, 이동 키를 누른 채 창 전환 후 복귀 시 키 해제·일시정지, Chrome 또는 Edge 실브라우저
