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

PR 단계 빌드 결과와 첫 배포 결과는 실행 후 이 절에 기록한다.
