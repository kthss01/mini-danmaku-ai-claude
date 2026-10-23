# tests/web-play

세션 5(이슈 #8)의 웹 통합 QA 증거를 보관한다. 검증 항목과 판정 기준은 [docs/web/QA.md](../../docs/web/QA.md)에 있다.

## 구성

| 경로 | 역할 |
| --- | --- |
| `EVIDENCE_TEMPLATE.md` | 검증 1회분 기록 양식. 복사해서 `evidence/` 아래에 작성 |
| `evidence/` | 실제 검증 기록. 파일 이름은 `YYYY-MM-DD-<브라우저>-<메인 커밋 7자리>.md`. 공식 판정은 `2026-10-24-chrome-official-fd6f865.md`, 나머지 `explore` 기록은 기존 산출물로 한 탐색 기록 |
| `collect-env.ps1` | OS·브라우저·커밋·도구 버전과 작업 트리 상태, 산출물 해시를 수집하는 읽기 전용 스크립트 |

## 규칙

- 증거 없는 항목은 `미검증`으로 둔다. 추정으로 `성공`을 쓰지 않는다.
- 스크린샷·로그 등 큰 파일은 Git에 넣지 않고, 기록에는 파일 이름과 확인한 내용 요약만 남긴다.
- 기록마다 검증한 메인 커밋과 `game/taisei` 커밋을 함께 적는다. 다른 PR 머지로 조합이 바뀌면 새 기록을 만든다.
- 결함은 기록에 남기고 담당 세션 이슈(#4 빌드, #5 런타임, #6 셸, #7 서버)에 링크한다.

- 커밋 SHA만 적지 않는다. 작업 트리의 미커밋 변경과 서빙한 산출물의 출처(빌드 시각·해시)를 함께 적고, 출처를 모르면 `출처 미확인`으로 둔다.
- 기존 로컬 빌드로 한 탐색 QA는 `탐색(기존 산출물)`로 표시하고, 공식 판정은 새 checkout 빌드로만 한다.

## 환경 수집

```powershell
.\tests\web-play\collect-env.ps1
.\tests\web-play\collect-env.ps1 -SiteDirectory build\web\site
```

두 번째 형태는 서빙 루트의 셸·게임 파일 SHA-256, 파일 수정 시각(빌드 시각 아님), `build-info.json` 요약(실제 빌드 커밋·시각·도구·미커밋)을 함께 출력한다. 루트 셸 + `game/` 배치와 평면 배치를 모두 인식한다.

검증 대상 저장소는 현재 위치가 속한 Git 저장소다. 다른 clone에 있는 이 스크립트로 QA clone을 기록할 때는 QA clone에서 실행하거나 `-RepositoryRoot <경로>`를 준다.

```powershell
Set-Location <QA clone>
& <이 스크립트 경로> -SiteDirectory build\web\site
```
