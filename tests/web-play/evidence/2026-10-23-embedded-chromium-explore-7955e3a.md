# 웹 플레이 검증 기록 — 탐색(기존 산출물)

- 검증일: 2026-10-23 20:43~20:55 (KST)
- 검증자: Claude 세션 5 (모델 claude-fable-5-1, 노력치 high)
- 담당 이슈: #8 (부모 #2)
- 결과 요약: 기존 feat/web-playable 로컬 빌드로 **탐색 QA**를 수행. 내장 Chromium에서 로딩→메뉴→스테이지 1 탄막 구간→이동·공격·저속·봄·일시정지·재개·게임오버 컨티뉴가 동작하고, 새로고침 후 IndexedDB에서 진행 데이터가 복원됨. 네트워크 실패 0건. 콘솔에 `FS.syncfs` 동시 실행 경고 반복. **공식 판정 아님** — 새 checkout 빌드가 아니고 산출물 manifest가 없어 QA-01은 미검증 유지.

## 1. 검증 대상 커밋

| 항목 | 값 |
| --- | --- |
| 메인 저장소 커밋 | `7955e3adaf0b12a114d5065e03e11720a464080e` (main, PR #9 머지 직후) — 단, 산출물은 이 커밋으로 빌드한 것이 아님 |
| `game/taisei` 커밋 | 세션 5 clone에서는 submodule 미초기화. 산출물 출처 브랜치의 gitlink는 `5668c41b41f7227d21fc80cf56997d4d30356ce7` |
| 포함된 PR (세션 1~4) | 없음. 세션 4 PR #10(head a145b64)의 `serve-web.py`·`check-web-assets.py`를 scratchpad로 복사해 사용(미머지, Codex 수정 요청 3건 있음) |
| checkout 방법 | 세션 5 전용 clone `mini-danmaku-ai-claude-integration`, 브랜치 `test/web-integration` |
| 검증 종류 | **탐색(기존 산출물)** |

### 1-1. 작업 트리 상태

```text
git status --porcelain: 0개 항목 (이 기록 파일과 collect-env.ps1 수정 전 기준)
git submodule status --recursive:
-5668c41b41f7227d21fc80cf56997d4d30356ce7 game/taisei
```

### 1-2. 산출물 출처 (provenance)

| 항목 | 값 |
| --- | --- |
| 서빙 루트 경로 | `build/explore-taisei-web` (Git 제외). 메인 clone `build/taisei-web`를 robocopy로 복사 |
| 생성 방법 | **기존 산출물 재사용**. 메인 clone의 미커밋 `feat/web-playable` 작업(`scripts/build-web.ps1`, emsdk 5.0.3, fork 5668c41b)으로 생성된 것으로 보이나 manifest가 없어 빌드 커밋·시각은 **출처 미확인** |
| 빌드 시각 | 미확인. 파일 수정 시각은 `taisei.wasm` 2026-10-23 20:18:47 (복사 전 원본 기준) |
| 빌드 도구 버전 | 미확인(빌드 로그 없음). 출처 스크립트의 설정값은 emsdk 5.0.3, 이미지 `taiseiproject/linux-toolkit:20260804` |
| manifest 또는 버전 파일 | 없음 |
| `taisei.html` SHA-256 | `113240a898a555b79b8dcfa49c75fe5aa89a68831c377431347e8127ca3ac555` (12,168 bytes) |
| `taisei.js` SHA-256 | `3e7ed5b785d039c22c67bb87a70b36ee01d3b96202ff715643d7e97eb33c8d64` (100,933 bytes) |
| `taisei.wasm` SHA-256 | `eb97b68b104ea960f9b5e4b8d219ec5168a96ba18958f4ac824a14abd3b10558` (4,538,726 bytes) |
| `data/` | 529개, 207.1 MB |

출처 미확인이므로 QA-01은 `성공`으로 표시하지 않는다.

## 2. 환경

| 항목 | 값 |
| --- | --- |
| OS | Microsoft Windows 11 Home 10.0.26200 |
| 브라우저·버전 | Claude 데스크톱 앱 내장 Chromium(브라우저 패널). 사용자 Chrome 155.0.8059.86 / Edge 155.0.4283.62는 **이번 탐색에서 사용하지 않음** |
| GPU | AMD Radeon 780M, NVIDIA GeForce RTX 4060 Laptop GPU (실제 사용 GPU 미확인) |
| 해상도·배율 | 패널 뷰포트 800×600(스크린샷 프레임), 창 내부 높이 768 |
| Docker / 빌드 이미지 | 이번 기록에서는 빌드하지 않음 |
| emsdk 버전 | 미확인(출처 스크립트 설정값 5.0.3) |
| Python 버전 | 3.12.2 (서버 실행) |
| 렌더러 | 콘솔 로그 `Renderer backend gles30 initialized` |

## 3. 실행 명령과 결과

```text
python -I <scratchpad>/s4/serve-web.py --root build/explore-taisei-web --port 8090
→ 127.0.0.1:8090 바인딩, index.html 제공 (PR #10 a145b64의 스크립트 사본)

python -I <scratchpad>/s4/check-web-assets.py --root build/explore-taisei-web --url http://127.0.0.1:8090 --sample-data 10
→ 통과 (오류 0, 경고 0). WASM 유효(섹션 11개), pthreads 요구 없음, data/ 529개 207.1 MiB, HTTP 검사 21건 실패 0
   (알려진 도구 결함: Codex가 PR #10에 지적한 3건 — 루트 밖 경로 차단 미완성, 대소문자 불일치 후 crash, 진입 HTML 404 통과. 이 결과는 그 범위에서 제한적)

curl -I http://127.0.0.1:8090/taisei.wasm → 200, Content-type: application/wasm, Cache-Control: no-store, X-Content-Type-Options: nosniff
curl http://127.0.0.1:8090/does-not-exist → 404
```

접속 URL: `http://127.0.0.1:8090/` → `게임 시작` 링크 → `http://127.0.0.1:8090/taisei.html` (로컬 전용)

## 4. QA 항목별 결과 (탐색)

이 기록은 **탐색(기존 산출물)** 이므로 여기의 `성공`도 공식 판정이 아니다. `docs/web/QA.md`의 공식 상태는 통합 후 새 checkout 검증 전까지 `미검증`으로 유지한다. 성공 기준을 일부만 확인한 항목은 `미검증`으로 두고 확인한 하위 동작과 남은 동작을 증거 칸에 적는다.

| ID | 상태 | 증거 (관찰 내용) | 결함 이슈 |
| --- | --- | --- | --- |
| QA-01 | 미검증 | 새 checkout 빌드 아님, manifest 없음 | |
| QA-02 | 미검증 | 빌드하지 않음 | |
| QA-03 | 미검증 | 확인: PR #10(a145b64) 서버로 127.0.0.1:8090 바인딩, 안내 URL로 index 응답. 남음: 문서의 종료 방법으로 종료 후 포트 해제 확인 | |
| QA-04 | 성공 | `.wasm` → `application/wasm`, 없는 경로 404, data/ 요청 500건 이상 전부 200 | |
| QA-05 | 미검증 | 오류 상황(산출물 없음·포트 충돌) 미실행 | |
| QA-10 | 성공 | 접속 직후 스피너·"Prefetching resources…" 진행 표시 후 인트로 컷신으로 전환(업스트림 셸은 시작 버튼 없음) | |
| QA-11 | 미검증 | 업스트림 `taisei.html`은 시작 버튼 없이 스크립트 load 즉시 `callMain`. 세션 3 셸 통합 후 재확인 | |
| QA-12 | 미검증 | 실패 상태 미실행 | |
| QA-13 | 성공 | 안내 키(화살표/Z/X/C/Shift/Esc)가 소스 기본 키와 일치. 컷신 건너뛰기 키 Ctrl은 안내에 없음(세션 3 참고) | #6 참고 |
| QA-14 | 미검증 | 확인: 서빙 루트에 `COPYING.txt` 존재, index.html에 링크. 남음: 음악·이미지 CC BY 고지가 포함 파일로 충족되는지 내용 확인 | |
| QA-15 | 미검증 | | |
| QA-20 | 성공 | `document.activeElement === canvas` 확인. 캔버스 클릭 후 키 입력이 게임에 전달 | |
| QA-21 | 성공 | `scrollHeight == innerHeight`(768), 방향키 입력 중 페이지 스크롤 없음 | |
| QA-22 | 미검증 | 키를 누른 채 창 전환을 자동화 도구로 재현할 수 없음 | |
| QA-23 | 미검증 | | |
| QA-30 | 성공 | Z로 메인 메뉴 → 난이도 선택(Easy) → 캐릭터 선택(Reimu) → 샷 타입 진행, 일시정지 메뉴 항목(Options/Return to Game/Restart/Stop) 표시·선택. 취소(X)는 일시정지 메뉴에서 미확인 → 아래 2차 탐색에서 보강 | |
| QA-31 | 성공 | 스테이지 1 진입, 적·탄 출현, HUD(Score/Lives/Spell Cards/Power) 표시 | |
| QA-32 | 미검증 | 확인: ←/→/↑ 입력으로 위치 변화. 남음: ↓ 방향 | |
| QA-33 | 성공 | Z 입력으로 샷 발사, 적 격파, 파워 아이템 드롭, Score 255→1,019 증가 | |
| QA-34 | 미검증 | 확인: Shift+← 입력 시 피격 판정 표시(히트박스 원). 남음: 속도 감소(스크린샷으로 정량 확인 불가) | |
| QA-35 | 성공 | X 입력 후 봄 이펙트와 탄 소거 관찰 | |
| QA-36 | 성공 | Esc로 "Game Paused" 메뉴, Z(Return to Game)로 재개 | |
| QA-37 | 미검증 | 오디오 드라이버 `emscripten` 초기화와 HUD "BGM: The Fog Invites Unseen Mischief" 표시 확인. **실제 소리 청취는 자동화로 불가** → 사용자 확인 필요 | |
| QA-38 | 미검증 | 구간 합계 약 3분(아래 5절). 5분 미만 | |
| QA-39 | 미검증 | HUD FPS 표시 60.00 / 61.26 / 59.10 fps 관찰(순간값). 30초 이상 연속 측정 미수행 | |
| QA-40 | 미검증 | 옵션 변경 미수행 | |
| QA-41 | 미검증 | 리플레이 저장 미수행 | |
| QA-42 | 성공 | 게임오버·컨티뉴 후 F5 재로딩 → `Loaded persistent storage from IndexedDB`, 인트로 컷신 없이 메인 메뉴 표시(진행 데이터 복원). IndexedDB `/persistent` v21 존재 | |
| QA-43 | 미검증 | 확인: 게임오버 → Continue(5)로 재개 1회. 남음: 메뉴 복귀 후 재진입, 반복 진입 | |
| QA-44 | 성공 | 플레이 중 재로딩 후 정상 재시작, 콘솔 오류 0건(경고는 7절) | |
| QA-50 | 미검증 | README 웹 명령 아직 없음 | |
| QA-51 | 미검증 | WEB_SETUP 미작성 | |
| QA-52 | 미검증 | 세션 문서 미머지 | |

## 5. 플레이 로그 (QA-38, 누적 5분)

| 구간 | 시작 시각 | 종료 시각 | 길이 | 종료 사유 | 관찰 |
| --- | --- | --- | --- | --- | --- |
| 1 | 20:49 | 20:50 | 약 1분 | 피격 2회로 게임오버 → Continue | 자동화 입력은 키를 누른 채 유지할 수 없어 회피가 불가능 |
| 2 | 20:50 | 20:52 | 약 2분 | 탐색 종료(F5 재로딩) | 봄·일시정지·재개 확인 |

- 누적 플레이 시간(구간 합): 약 3분 (5분 미달, 탐색 기록이므로 QA-38 미검증)
- 콘솔 오류: 0건. 경고 `warning: 2 FS.syncfs operations in flight at once, probably just doing extra work` 반복(4회 이상), `The ScriptProcessorNode is deprecated` 1회
- 네트워크 실패(404·5xx·차단): 0건 (확인한 최근 400건 모두 200)

## 6. FPS 측정 (QA-39)

- 측정 방법: 게임 HUD 우하단 FPS 표시를 스크린샷으로 읽음(순간값)
- 측정 구간: 스테이지 1 초반
- 최소 / 평균 FPS: 순간값 59.10 / 60.00 / 61.26. 연속 측정 미수행
- 하락 구간과 원인 추정: 미측정

## 7. 결함과 미해결 사항

| 번호 | 증상 | 재현 절차 | 담당 세션 이슈 | 상태 |
| --- | --- | --- | --- | --- |
| 1 | 콘솔 `warning: 2 FS.syncfs operations in flight at once` 반복 | 플레이 중 저장 시점(게임오버·메뉴 전환)마다 발생 | #5 | 전달 예정(영향: 경고, 데이터 손상 미관찰) |
| 2 | `ScriptProcessorNode is deprecated` 경고 | 오디오 초기화 시 1회 | #5 | 정보(SDL emscripten 오디오 백엔드 특성) |
| 3 | 기존 `web/index.html`의 "게임 시작" 링크가 `taisei.html`(평면)로 고정. 세션 1 계약은 `game/taisei.html` | 통합 배치 후 접속 | #6 | 세션 3이 계약에 맞춰 구현 중이므로 참고만 |
| 4 | PR #10 서버·검사 도구의 Codex 지적 3건(루트 밖 경로, 대소문자 crash, 진입 404 통과) | Codex 검토 댓글 참조 | #7 | 수정본으로 재검증 필요 |

## 8. 완료 차단 판정

- 탐색에서 새로 관찰한 차단 결함: 없음. **최종 차단 판정은 미완료**(소리·blur 키 해제·설정/리플레이 저장 등 필수 검증이 남아 있음)
- 비차단 항목(범위·원인 명시): 소리 청취는 사람이 확인해야 함. 키 홀드가 필요한 회피·연속 공격은 자동화 한계로 미검증
- 부모 #2 완료 조건 충족 여부: **미충족**. 공식 검증(통합 main 새 checkout 빌드, Chrome/Edge, 누적 5분, 설정·리플레이 저장)은 아직 수행하지 않음
