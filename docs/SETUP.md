# Taisei 로컬 환경 구축

검증일: 2026-10-23
대상: Windows 11 x64에서 Taisei Windows x64 원본 빌드 및 초기 실행

## 검증 결과

| 항목 | 결과 |
| --- | --- |
| Taisei fork 접근 | 성공: `https://github.com/kthss01/taisei.git` |
| 공식 upstream 접근 | 성공: `https://github.com/taisei-project/taisei.git` |
| 고정 커밋 | `5668c41b41f7227d21fc80cf56997d4d30356ce7` (`master`) |
| 하위 submodule | `basis_universal`, `SDL_GameControllerDB`, `koishi`, `openlibm` 초기화 완료 |
| 빌드 | Windows x64 교차 빌드 및 설치 성공 |
| CLI 확인 | `Taisei v1.5-dev release`, 도움말 출력 성공 |
| 초기 실행 | 960×720 창 생성, GL 3.3 렌더러·WASAPI 오디오·리소스 초기화 확인 |
| 전체 수동 플레이 | 이번 단계에서는 미검증 |

`taisei.exe`의 검증 시 SHA-256은 `84269A94F50CF08D2421B86362CE7F54A6E3BD1BD12D6519F85837CEA023E2AE`였다. 빌드 도구나 의존성이 달라지면 바이너리 해시는 달라질 수 있다.

## 소스 구성

메인 저장소는 사용자 fork를 Git submodule로 고정한다.

```text
origin   https://github.com/kthss01/mini-danmaku-ai-claude.git
game/taisei origin   https://github.com/kthss01/taisei.git
game/taisei upstream https://github.com/taisei-project/taisei.git
```

`upstream`은 submodule의 로컬 Git 설정이므로 새 clone에서는 설정 스크립트가 다시 등록한다.

## 확인한 환경

- Windows 11 Home 64-bit, 빌드 `10.0.26200`
- CPU: AMD Ryzen 7 7840HS, 8코어/16스레드
- GPU: AMD Radeon 780M, NVIDIA GeForce RTX 4060 Laptop GPU
- Git for Windows 2.44.0
- Docker Desktop Engine 26.1.1
- 빌드 이미지: `taiseiproject/linux-toolkit:20260804`
- 이미지 digest: `sha256:1104b4a5bba4d7f03f7d03cd6990571b476afe276c97d9d8074c33b1834474b2`
- 컨테이너 내부: Meson 1.11.2, Python 3.13.14, llvm-mingw Clang 22.1.8

호스트에 Meson, Ninja, CMake, GCC/Clang, pkg-config가 없었고 일반 Ubuntu WSL도 설치되어 있지 않았다. 공식 빌드 문서는 Windows에서 MSVC 대신 Linux/WSL의 `llvm-mingw` 교차 컴파일을 권장하므로, Taisei CI와 같은 Docker 이미지 및 cross-file을 사용했다.

## 처음 받기

```powershell
git clone https://github.com/kthss01/mini-danmaku-ai-claude.git
Set-Location mini-danmaku-ai-claude
git submodule update --init --recursive
.\scripts\setup-taisei.ps1
```

설정 스크립트는 다음을 검증한다.

- `game/taisei`의 `origin`이 사용자 fork인지 확인
- 하위 submodule 초기화
- 공식 저장소를 `upstream`으로 추가 또는 갱신
- Taisei 저장소에만 `core.autocrlf=false` 적용

## 빌드

Docker Desktop을 실행한 뒤 저장소 루트에서 실행한다.

```powershell
.\scripts\build-taisei.ps1
```

스크립트는 현재 submodule 커밋을 읽고 컨테이너 내부의 임시 LF checkout에서 다음 공식 CI 설정으로 빌드한다.

```text
misc/ci/common-options.ini
misc/ci/forcefallback.ini
misc/ci/windows-llvm_mingw-x86_64-build-test-ci.ini
```

결과는 `build/taisei-windows-x64/`에 설치된다. 기존 결과를 명시적으로 교체할 때만 다음을 사용한다.

```powershell
.\scripts\build-taisei.ps1 -Force
```

빌드 산출물과 런타임 데이터는 `.gitignore`로 제외된다.

## 실행

```powershell
.\scripts\run-taisei.ps1
```

기본 렌더러는 `gl33`이다. 저장 데이터와 로그는 프로젝트 전역 사용자 설정과 섞이지 않도록 `build/taisei-windows-x64/runtime-data/`에 기록된다.

직접 확인할 때는 다음 명령도 사용할 수 있다.

```powershell
.\build\taisei-windows-x64\taisei.exe --version
.\build\taisei-windows-x64\taisei.exe --help
```

## 이번 실행에서 확인한 범위

15초 동안 실제 프로그램을 실행했으며 다음 증거를 확인했다.

- 프로세스가 종료되지 않고 Windows에서 `Responding=True`
- 창 제목 `Taisei Project v1.5-dev`와 유효한 window handle
- 로그의 `Renderer backend gl33 initialized`
- 960×720 창 생성 및 video subsystem 초기화
- WASAPI audio subsystem 초기화
- `Initialization complete` 이후 게임 리소스 로딩

따라서 빌드 성공뿐 아니라 로컬 GUI 초기 실행까지 확인했다. 다만 키보드 조작, 스테이지 진입, 리플레이 저장을 포함한 전체 수동 플레이는 아직 확인하지 않았다.

## 문제 해결

### `env: 'python3\r': No such file or directory`

Windows Git이 Taisei의 실행 스크립트를 CRLF로 체크아웃하면 Linux 컨테이너에서 shebang을 해석하지 못한다. 검증 중 첫 `meson setup`에서 이 오류가 발생했다. 제공한 빌드 스크립트는 컨테이너 안에 임시 LF checkout을 만들어 이 문제를 피한다. Taisei 작업 트리에는 설정 스크립트가 `core.autocrlf=false`를 적용한다.

### Docker daemon 연결 오류

`docker info`가 named pipe 연결 오류를 출력하면 Docker Desktop을 시작하고 엔진 준비가 끝난 후 다시 실행한다.

### 최초 실행의 로그 메시지

격리된 저장 디렉터리의 첫 실행에서는 아직 `progress.zst`와 사용자 컨트롤러 매핑 파일이 없다는 로그가 남는다. 검증 실행에서는 `res/shader/global.pp`를 찾지 못했다는 오류도 기록됐지만, 이후 `Initialization complete`와 응답 가능한 게임 창까지 진행됐다. 게임이 실제로 종료되거나 렌더링에 문제가 생기면 `build/taisei-windows-x64/runtime-data/log.txt`를 우선 확인한다.

## 라이선스와 공식 자료

- 빌드 지침: `game/taisei/doc/BUILD.rst`
- 프로젝트 안내: `game/taisei/README.rst`
- 라이선스: `game/taisei/COPYING.txt`
- 공식 저장소: <https://github.com/taisei-project/taisei>

Taisei 소프트웨어는 `COPYING.txt`에 기재된 허용적 라이선스를 사용한다. 같은 파일에서 원본 사운드트랙과 캐릭터 초상화 일부는 CC BY 4.0으로 별도 고지한다. 배포 또는 영상 공개 전에는 코드뿐 아니라 음악·이미지별 고지 조건도 다시 확인해야 한다.
