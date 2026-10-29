# Taisei 웹 버전 빌드·실행 안내

검증일: 2026-10-24 · 검증 커밋: 메인 `fd6f8659b945dcb7fcf1832f1e734585345477f0`, Taisei `f59212b72df3b68459b4677a6200e42be700078a`
추적 이슈: [#2](https://github.com/kthss01/mini-danmaku-ai-claude/issues/2) · 통합 QA: [#8](https://github.com/kthss01/mini-danmaku-ai-claude/issues/8)

Taisei를 Emscripten(WebAssembly)으로 빌드해 이 PC의 브라우저에서 플레이하는 절차다. 아래 명령은 새 clone에서 그대로 실행해 확인했다. 검증 근거는 [공식 검증 기록](../tests/web-play/evidence/2026-10-24-chrome-official-fd6f865.md)에 있다.

## 1. 준비

| 항목 | 요구 | 검증한 버전 |
| --- | --- | --- |
| OS | Windows 10/11 x64, PowerShell | Windows 11 Home 10.0.26200, Windows PowerShell 5.1 |
| Git | submodule 지원 | Git for Windows 2.44.0 |
| Docker Desktop | 실행 중이어야 함 | Docker 26.1.1 |
| Python | Python 3(로컬 서버·검사 도구). 최소 버전은 확인하지 않음 | 3.12.2 |
| 브라우저 | WebGL 2, WebAssembly SIMD를 지원하는 Chrome 91+ 또는 Edge | Chrome 155.0.8059.86 |
| 디스크 | `build/web` 약 428 MB(install + site), emsdk Docker volume 별도 | |

빌드 도구는 스크립트가 고정한다. 직접 설치할 필요가 없다.

| 도구 | 고정값 |
| --- | --- |
| 빌드 이미지 | `taiseiproject/linux-toolkit:20260804@sha256:1104b4a5bba4d7f03f7d03cd6990571b476afe276c97d9d8074c33b1834474b2` |
| emsdk / Emscripten | `5.0.3` (Docker volume `taisei-emsdk-5.0.3`에 캐시) |
| Meson 옵션 | 공식 CI와 같은 cross-file + `-Dbuild.cpp_std=gnu++14` |

## 2. 빌드

PowerShell에서 실행한다.

```powershell
git clone --recurse-submodules https://github.com/kthss01/mini-danmaku-ai-claude.git
Set-Location mini-danmaku-ai-claude
.\scripts\setup-taisei.ps1
.\scripts\build-web.ps1
```

- 결과: `build/web/site/`(서빙 루트). `build/`는 Git에서 제외된다.
- 검증 시 소요 시간: 238초(emsdk volume이 이미 있을 때). 처음에는 emsdk와 LLVM을 내려받아 더 걸린다.
- 이미 빌드한 clone에서 다시 컴파일할 때는 `.\scripts\build-web.ps1 -Force`, 컴파일 없이 셸(`web/`)만 다시 패키징할 때는 `-PackageOnly`를 쓴다.
- 빌드 출처는 `build/web/site/build-info.json`에 기록된다(`build`: 실제 빌드 커밋·시각·도구, `packaging`: 패키징 정보, `site`: 주요 파일 SHA-256).

산출물 구성:

```text
build/web/site/
├── index.html          # 진입 페이지 → game/index.html 로 이동
├── COPYING.txt         # 라이선스 고지
├── build-info.json
└── game/
    ├── index.html, shell.js, shell.css, shell-config.js   # 웹 셸(로딩·시작·오류·조작 안내)
    ├── taisei.html, taisei.js, taisei.wasm               # 게임(taisei.html 은 업스트림 셸)
    ├── data/           # 리소스 529개(약 207 MB, 파일 이름 = SHA-256)
    └── COPYING.txt 외 정적 파일
```

자세한 빌드 계약은 [docs/web/BUILD.md](web/BUILD.md)에 있다.

## 3. 실행

```powershell
python scripts/serve-web.py
```

출력:

```text
serve-web: 루트 ...\build\web\site
serve-web: 격리 헤더(COOP/COEP) 꺼짐
serve-web: http://127.0.0.1:8080/ 에서 제공 중 (종료: Ctrl+C)
```

브라우저에서 다음 주소를 연다. **이 PC에서만 열리는 로컬 주소이며 공개 URL이 아니다.**

```text
http://127.0.0.1:8080/
```

1. 페이지가 `game/index.html`로 이동하고 조작 안내와 "게임 시작" 버튼이 보인다.
2. "게임 시작"을 누르면 게임 코드와 리소스를 내려받는다. 첫 실행은 수백 MB를 받고 브라우저 저장소(IndexedDB)에 캐시한다.
3. 게임 화면이 뜨면 화면을 한 번 클릭하거나 키를 눌러 포커스와 소리를 켠다.
4. 종료는 서버를 띄운 터미널에서 `Ctrl+C`.

자주 쓰는 서버 옵션:

| 옵션 | 용도 |
| --- | --- |
| `--port <n>` | 8080이 사용 중일 때. `--port 0`은 빈 포트 자동 선택 |
| `--root <dir>` | 다른 산출물 디렉터리 제공 |
| `--quiet` | 요청 로그 생략 |

오류: 산출물이 없으면 종료 코드 2, 포트가 사용 중이면 종료 코드 3과 안내 문구를 출력한다. 자세한 동작은 [docs/web/SERVING.md](web/SERVING.md).

빌드 없이 플레이하려면 GitHub Pages 공개 주소 https://kthss01.github.io/mini-danmaku-ai-claude/ 를 연다. `main`의 웹 관련 변경이 자동으로 빌드·배포된다. 배포 절차는 [docs/web/PAGES.md](web/PAGES.md)에 있다.

## 4. 조작

| 동작 | 기본 키 |
| --- | --- |
| 이동 | 방향키 |
| 공격 · 메뉴 선택 | `Z` |
| 봄 · 메뉴 취소 | `X` |
| 파워 서지 | `C` |
| 저속 이동(피격 판정 표시) | `Shift`(왼쪽) |
| 대화 건너뛰기 | `Ctrl`(왼쪽) |
| 일시정지 · 메뉴 뒤로 | `Esc` |
| 소리 켜기/끄기 | `M` |

키는 게임 메뉴 Options → Customize controls에서 바꿀 수 있다. `F11`(전체 화면)과 `F12`(개발자 도구)는 브라우저가 처리한다.

### 언어

- 게임 옵션의 **Language**(한국어 UI에서는 "언어 (Language)") 항목에서 `System` / `English` / `한국어` / `Deutsch` / `Français` / `简体中文` 중 고른다. 한국어 번역 범위와 용어는 [docs/web/L10N.md](web/L10N.md)에 있다.
- 기본값 `System`은 브라우저 언어를 따른다. **한국어 브라우저(`ko`, `ko-KR`)는 처음부터 한국어로 시작한다.** 그 밖의 언어는 영어로 시작한다(번역이 있는 독일어·프랑스어(캐나다)·중국어(간체) 브라우저는 해당 언어).
- 선택은 즉시 적용되고, 다른 설정처럼 옵션 메뉴를 나갈 때 IndexedDB에 저장된다.

## 5. 저장

- 설정·진행도·하이스코어·리플레이는 브라우저 IndexedDB(`/persistent`)에 저장된다. 서버에는 저장하지 않는다.
- 저장은 옵션 메뉴를 나갈 때, 스테이지가 끝날 때, 리플레이를 저장할 때 일어난다. 옵션 메뉴 안이나 스테이지 도중에 새로고침하면 그 사이의 변경은 남지 않는다.
- 저장 데이터는 주소(호스트·포트)별로 따로 관리된다. 포트를 바꾸면 빈 저장소에서 시작하고 리소스를 다시 내려받는다.
- 브라우저의 사이트 데이터를 지우면 저장 데이터와 리소스 캐시가 함께 지워진다.

## 6. 검증 범위

2026-10-24 공식 검증 결과 요약이다. 상세 판정은 [QA 매트릭스](web/QA.md)와 [공식 검증 기록](../tests/web-play/evidence/2026-10-24-chrome-official-fd6f865.md)에 있다.

| 범위 | 결과 | 브라우저 |
| --- | --- | --- |
| 새 clone 빌드·패키징 | 성공(종료 코드 0, 238초) | - |
| 서버 실행·MIME·404·오류 종료 코드 | 성공 | - |
| 산출물 해시·참조 검사(진입 3종) | 성공(HTTP 539~543건 실패 0) | - |
| 로딩 진행·시작 버튼·로더 오류 화면 | 성공 | Chrome, 내장 Chromium |
| WebGL 2 미지원 안내 | 성공(모의: 셸 사본에서 WebGL 2 컨텍스트를 막아 확인) | 내장 Chromium |
| 메뉴·스테이지 진입·좌우 이동·공격·스크롤 방지·포커스 | 성공 | Chrome |
| 4방향 이동·일시정지/재개 | 성공 | 내장 Chromium |
| 누적 5분 탄막 플레이(스테이지 1 클리어, 스테이지 3 진입) | 성공(약 307초) | 내장 Chromium |
| 설정 저장 후 새로고침 유지 | 성공 | Chrome |
| 리플레이 저장 → 새로고침 → 재생 | 성공 | 내장 Chromium |
| 진행 데이터 유지·Continue 재진입·새로고침 | 성공 | Chrome, 내장 Chromium |
| 실제 소리 청취 | **미검증**(사람이 확인해야 함) | - |
| 키를 누른 채 다른 창으로 전환 시 키 해제 | **미검증**(자동화로 재현 불가) | - |
| Chrome 창을 앞에 둔 상태의 HUD FPS | **미검증**(측정한 것은 rAF 콜백/초뿐: 내장 Chromium 평균 120.1) | - |
| 저속 이동의 피격 판정 표시, 봄의 탄 소거 판독 | **미검증**(속도 감소·봄 발동·봄 개수 감소는 확인) | 내장 Chromium |
| 서버 `Ctrl+C` 종료 | **미검증**(자동화로 신호를 전달하지 못함) | - |
| 웹 셸 전체 화면 버튼 | 미검증(완료 조건 외, 비차단) | - |

"내장 Chromium"은 Claude 데스크톱 앱의 브라우저 패널(Chromium 152)이다. 같은 공식 산출물로 검증했지만 Chrome과 별개 브라우저이므로 구분해 적었다.

**완료 판정은 보류 중이다.** 굵게 표시한 미검증 항목은 사람이 확인해야 하며, 한 번에 확인하는 절차는 [공식 검증 기록](../tests/web-play/evidence/2026-10-24-chrome-official-fd6f865.md) 9절에 있다.

## 7. 알려진 제약

- **창이 가려지면 느려질 수 있음:** 이 PC에서 Chrome 창이 다른 창에 가려졌을 때 rAF 콜백이 초당 1~2회로 떨어지고 게임 시간도 느려졌다. 게임 없는 텍스트 페이지도 같아 브라우저의 갱신 억제로 추정한다(모든 환경에서 확인한 원인은 아니다). 플레이할 때는 브라우저 창을 앞에 둔다.
- **첫 실행 다운로드:** 처음에는 리소스 약 207 MB를 내려받아 IndexedDB에 저장한다. 로컬 서버에서는 수십 초 안에 끝난다.
- **스레드 없음:** pthreads를 쓰지 않는 빌드라 COOP/COEP 헤더가 필요 없다. 일부 작업은 메인 스레드에서 동기로 처리된다.
- **콘솔 경고:** `FS.syncfs operations in flight at once` 경고가 저장 시점마다 나온다. 데이터 손상은 관찰하지 못했다([#5](https://github.com/kthss01/mini-danmaku-ai-claude/issues/5)).
- **게임패드:** 웹 빌드에 게임패드 매핑 파일이 포함되지 않는다. 키보드만 검증했다.
- **새 clone 직후 dirty 표시:** Git for Windows 기본 설정으로 clone하면 `setup-taisei.ps1` 뒤 `game/taisei`가 줄바꿈 차이로 수정됨으로 보이고 빌드 출처에 기록된다. 빌드 결과에는 영향이 없다. 수정 PR #25 검토 중([#4](https://github.com/kthss01/mini-danmaku-ai-claude/issues/4)).
- **wasm 바이트 재현성:** 같은 커밋으로 빌드해도 `taisei.wasm` 해시는 매번 다를 수 있다. 크기와 `taisei.js` 해시는 같았다.
- **로컬 전용:** 서버는 `127.0.0.1`에만 바인딩하는 개발용 HTTP/1.0 서버다. 공개 배포에 쓰지 않는다. 공개 호스팅 시 필요한 MIME·경로 조건은 [docs/web/SERVING.md](web/SERVING.md)를 참고한다. 공개 배포는 GitHub Pages로 한다([docs/web/PAGES.md](web/PAGES.md)).

## 8. 라이선스

Taisei 코드는 `COPYING.txt`의 허용적 라이선스(MIT 형식)를 따른다. 원본 사운드트랙은 Tuck V의 CC BY 4.0, 캐릭터 초상화 일부는 별도 CC BY 4.0 고지가 있다. 산출물의 루트와 `game/`에 `COPYING.txt`가 포함되고 게임 셸 하단에 링크가 있다. 영상·스크린샷을 공개할 때는 음악·이미지별 출처 표기를 다시 확인한다.

## 9. 관련 문서

| 문서 | 내용 |
| --- | --- |
| [docs/web/BUILD.md](web/BUILD.md) | 빌드 스크립트, 산출물 계약, 출처 기록 |
| [docs/web/RUNTIME.md](web/RUNTIME.md) | 런타임 구조, 입력·오디오·저장, fork 수정 |
| [docs/web/SHELL.md](web/SHELL.md) | 웹 셸 상태 흐름, 입력·포커스 정책 |
| [docs/web/SERVING.md](web/SERVING.md) | 서버 옵션, 자산 검사, 공개 배포 조건 |
| [docs/web/PAGES.md](web/PAGES.md) | GitHub Pages 자동 빌드·배포 |
| [docs/web/L10N.md](web/L10N.md) | 한국어 번역 범위·용어표·말투 |
| [docs/web/QA.md](web/QA.md) | QA 항목과 판정 |
| [docs/SETUP.md](SETUP.md) | Windows 데스크톱 빌드 |
