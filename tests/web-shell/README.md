# 웹 셸(web/) 검증 도구

`web/`의 로딩·시작·게임 화면·오류 상태를 실제 게임 없이(mock) 또는 실제 WASM 산출물과 함께 로컬 HTTP로 확인하기 위한 도구입니다. 세션 1의 빌드·패키징 명령이나 세션 4의 서버를 대체하지 않습니다.

## 구성

- `mock-taisei.js`: 실제 `taisei.js`와 같은 계약(전역 `createTaisei`, 인스턴스의 `initFilesystem`/`callMain`, `Module.setStatus`/`onFirstFrame`/`onAbort`/`onExit`)으로 동작하는 가짜 로더. URL 쿼리 `?mock=<시나리오>`로 상태 전환을 재현한다.
- `stage-site.ps1`: `web/`와 게임 산출물(또는 mock)을 한 디렉터리로 모은다.

## mock 검증

```powershell
.\tests\web-shell\stage-site.ps1 -Out $env:TEMP\taisei-shell-mock -Mock
python -m http.server 8091 --bind 127.0.0.1 --directory $env:TEMP\taisei-shell-mock
```

브라우저에서 `http://127.0.0.1:8091/index.html?mock=<시나리오>`를 연다.

| 시나리오 | 재현 내용 | 기대 상태 |
| --- | --- | --- |
| `ok`(기본) | 준비 진행 → 첫 프레임 → 리소스 프리페치 진행 → 플레이 | `playing`, HUD에 진행 표시 후 사라짐 |
| `slow` | `ok`와 같고 단계 지연이 길다(진행 표시를 눈으로 확인) | `playing` |
| `reject` | wasm 내려받기 실패로 팩터리 Promise 거부 | `error` |
| `abort` | Emscripten abort(`onAbort` 후 RuntimeError) | `error`(abort 메시지) |
| `contract` | 인스턴스에 `callMain` 없음 | `error`(계약 불일치) |
| `nofactory` | 로더가 `createTaisei`를 정의하지 않음 | `error`(계약 불일치) |
| `crash` | 첫 프레임 뒤 비동기 예외 | `error`, 게임 화면은 뒤에 남음 |
| `exit` | 첫 프레임 뒤 `onExit(0)` | `exited` |
| `download-fail` | 로딩 중 리소스 내려받기 실패 메시지(`printErr`) | `loading`/`playing` 상태에 경고 표시 |

로더 404는 스테이징 디렉터리의 `taisei.js`를 지운 뒤 시작 버튼을 눌러 확인한다(브라우저 캐시 때문에 새로고침이 필요할 수 있다).

mock에는 `background.webp`, `favicon.ico`가 없으므로 해당 404는 정상이다.

## 실제 WASM 검증

```powershell
.\tests\web-shell\stage-site.ps1 -Out $env:TEMP\taisei-shell-real -Game build\taisei-web
python -m http.server 8137 --bind 127.0.0.1 --directory $env:TEMP\taisei-shell-real
```

`-Game`에는 `taisei.js`, `taisei.wasm`, `data/`가 있는 빌드 산출물 디렉터리를 준다. 결과와 검증 범위는 `docs/web/SHELL.md`에 기록한다.

## 셸 상태 읽기

페이지의 `window.taiseiShell`에서 `state`(`checking`/`unsupported`/`ready`/`loading`/`playing`/`error`/`exited`), `hadFirstFrame`, `errors`, `logLines`를 읽을 수 있다. 자동화 검증은 이 값을 기준으로 삼는다.
