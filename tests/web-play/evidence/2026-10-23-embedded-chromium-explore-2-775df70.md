# 웹 플레이 검증 기록 — 탐색 2차(기존 산출물, PR #10 머지 도구)

- 검증일: 2026-10-23 21:02~21:07 (KST)
- 검증자: Claude 세션 5 (모델 claude-fable-5-1, 노력치 high)
- 담당 이슈: #8 (부모 #2)
- 결과 요약: 1차 탐색 기록(`2026-10-23-embedded-chromium-explore-7955e3a.md`)과 같은 산출물을 PR #10 머지 커밋(775df70)의 `serve-web.py`·`check-web-assets.py`로 다시 제공하고, 남아 있던 탐색 항목을 보강했다. **옵션 변경 → 새로고침 후 유지(QA-40), 리플레이 저장 → 새로고침 후 목록·재생(QA-41), 아래 방향 이동(QA-32), 일시정지 취소 키, 게임오버 후 Give up → 메뉴 복귀 → 재진입**을 관찰했다. **공식 판정 아님**(새 checkout 빌드 아님, manifest 없음). 모든 QA 공식 상태는 `미검증` 유지.

## 1. 검증 대상 커밋

| 항목 | 값 |
| --- | --- |
| 메인 저장소 커밋 | 작업 브랜치 `test/web-integration` (base `7955e3a`). 서버·검사 도구는 `origin/main` `775df70`(PR #10 머지, head f8188b9)에서 가져옴 |
| `game/taisei` 커밋 | 세션 5 clone에서는 submodule 미초기화. 산출물 출처 브랜치의 gitlink는 `5668c41b` |
| 포함된 PR (세션 1~4) | #10(머지, 775df70). #11 #12 #13은 미머지 |
| checkout 방법 | 세션 5 전용 clone `mini-danmaku-ai-claude-integration` |
| 검증 종류 | **탐색(기존 산출물)** |

### 1-1. 작업 트리 상태

```text
git status --porcelain: 수정 중인 세션 5 담당 파일만 (tests/web-play/**). 산출물 build/explore-taisei-web는 Git 제외
git submodule status --recursive:
-5668c41b41f7227d21fc80cf56997d4d30356ce7 game/taisei
```

### 1-2. 산출물 출처 (provenance)

1차 기록과 동일한 디렉터리·해시. 요약:

| 항목 | 값 |
| --- | --- |
| 서빙 루트 경로 | `build/explore-taisei-web` (평면 배치: 루트에 `taisei.html`) |
| 배치 형태 | 평면 |
| 생성 방법 | 기존 산출물 재사용(메인 clone `feat/web-playable` 미커밋 빌드). **출처 미확인** |
| 빌드 시각 | 미확인(manifest 없음) |
| 파일 수정 시각 (`taisei.wasm`) | 2026-10-23 20:18:47 (참고용, 빌드 시각 아님) |
| 빌드 도구 버전 | 미확인(출처 스크립트 설정값 emsdk 5.0.3) |
| manifest | 없음 |
| 루트 `index.html` SHA-256 | `7ad3afc9ca1df0af36ad372fe35c8792876a513e3c2ecc48b5da3ec0e86bdb6d` (feat/web-playable의 안내 페이지, 세션 3 셸 아님) |
| `taisei.html` SHA-256 | `113240a898a555b79b8dcfa49c75fe5aa89a68831c377431347e8127ca3ac555` |
| `taisei.js` SHA-256 | `3e7ed5b785d039c22c67bb87a70b36ee01d3b96202ff715643d7e97eb33c8d64` |
| `taisei.wasm` SHA-256 | `eb97b68b104ea960f9b5e4b8d219ec5168a96ba18958f4ac824a14abd3b10558` |

## 2. 환경

1차 기록과 동일: Windows 11 10.0.26200, Claude 데스크톱 앱 내장 Chromium(브라우저 패널, 검증 중 패널이 숨김 상태였으나 rAF 63회/초·HUD 60.00 fps 확인), Python 3.12.2. 사용자 Chrome/Edge 미사용.

## 3. 실행 명령과 결과

```text
python -I <scratchpad>/s4/serve-web.py --root build/explore-taisei-web --port 8090   # origin/main 775df70 사본
→ 127.0.0.1:8090. 같은 포트를 재사용해 1차 기록의 IndexedDB(/persistent) 데이터를 이어받음

python -I <scratchpad>/s4/check-web-assets.py --root build/explore-taisei-web --url http://127.0.0.1:8090 --sample-data 10
→ 통과 (오류 0, 경고 0). entry-http: index.html 200 text/html(신규 검사), not-found 404, HTTP 검사 22건 실패 0
```

접속 URL: `http://127.0.0.1:8090/taisei.html` (로컬 전용)

## 4. QA 항목별 결과 (탐색)

1차 기록에서 바뀐 항목만 적는다. 나머지는 1차 기록과 같다.

| ID | 상태 | 증거 (관찰 내용) | 결함 이슈 |
| --- | --- | --- | --- |
| QA-03 | 미검증 | 확인: 775df70 서버로 제공, 이전 서버(a145b64) 프로세스 종료 후 같은 포트 재바인딩 성공(포트 해제 확인). 남음: 문서에 적힌 종료 방법(Ctrl+C) 그대로 수행 | |
| QA-04 | 성공 | 최신 검사 도구로 entry-http·404·MIME 재확인 | |
| QA-30 | 성공 | 메인 메뉴 Down/Up 이동, Options·Replays·Start Story 선택, X로 난이도 선택에서 메뉴로 복귀(취소). 스테이지 1 플레이 후 "Stage Practice" 항목 해금됨 | |
| QA-32 | 성공 | Up/Down/Left/Right 모두 캐릭터 위치 변화 확인(Up·Down은 이번 기록, Left·Right는 1차) | |
| QA-36 | 성공 | Esc 일시정지 → X(취소)로 재개. 1차에서는 Z(Return to Game)로 재개 | |
| QA-40 | 성공 | Options → SFX Volume 50% → Left×2 → 40% → X로 나가기(`Saved persistent storage to IndexedDB`) → F5 → Options 재진입 시 SFX Volume 40% 유지 | |
| QA-41 | 성공 | 게임오버 → Give up → "Save Replay?" Yes → 로그 `replay_save: Saving /persistent/storage/replays/taisei_20261023_21-04-05-359_stg1_reimuA_easy.tsr` → F5 → Replays 메뉴에 `2026-10-23 21:04 Player ReimuA Easy Stage 1` 표시 → 선택 시 재생(좌하단 "Replay: Player", 60 fps) | |
| QA-42 | 성공 | Give up으로 스테이지를 끝낸 뒤 F5 → Hi-Score 240 유지, Stage Practice 해금 유지. (참고: 스테이지 도중 F5는 커밋 전이라 하이스코어가 남지 않음 — 세션 2 RUNTIME.md의 커밋 시점 설명과 일치, 결함 아님) | |
| QA-43 | 성공 | 게임오버 → Give up → 메인 메뉴 → Start Story 재진입 → 스테이지 1 정상 시작(2회) | |

## 5. 플레이 로그 (QA-38, 누적 5분)

| 구간 | 시작 시각 | 종료 시각 | 길이 | 종료 사유 | 관찰 |
| --- | --- | --- | --- | --- | --- |
| 1 | 21:04 | 21:05 | 약 1분 | 피격 2회 게임오버 → Give up(리플레이 저장) | 키 홀드 불가로 회피 불가 |
| 2 | 21:06 | 21:07 | 약 20초 | 리플레이 재생 관찰(플레이 아님) | 재생 중 60 fps |

- 누적 플레이 시간(1차+2차 구간 합): 약 4분. 5분 미달 → QA-38 미검증 유지
- 콘솔 오류: 0건. 경고: `FS.syncfs operations in flight` 반복(1차와 동일)
- 네트워크 실패: 0건

## 6. FPS 측정 (QA-39)

- 측정 방법: HUD FPS 표시 + `requestAnimationFrame` 1초 카운트(63회)
- 측정 구간: 스테이지 1 초반, 리플레이 재생
- 순간값 60.00 fps. 연속 30초 측정은 미수행 → 미검증

## 7. 결함과 미해결 사항

| 번호 | 증상 | 재현 절차 | 담당 세션 이슈 | 상태 |
| --- | --- | --- | --- | --- |
| 1 | `FS.syncfs` 동시 실행 경고 반복 | 1차 기록 참조 | #5 | 전달함(이슈 #5 댓글) |
| 2 | 스테이지 도중 새로고침 시 하이스코어 미보존 | 스테이지 진행 중 F5 | #5 | 설계 동작(커밋 시점 제한). 문서에 제약으로 기재 예정, 결함 아님 |

## 8. 완료 차단 판정

- 탐색에서 새로 관찰한 차단 결함: 없음. **최종 차단 판정은 미완료**
- 사용자 확인이 필요한 항목(자동화 불가): (1) 실제 스피커로 BGM·효과음 청취, (2) 이동 키를 누른 채 다른 창으로 전환 후 복귀 시 캐릭터가 멈추는지, (3) Chrome 또는 Edge 실브라우저에서 동일 절차
- 부모 #2 완료 조건 충족 여부: **미충족**(공식 새 checkout 빌드·Chrome/Edge·누적 5분 미수행)
