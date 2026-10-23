# mini-danmaku-ai-claude

Taisei Project 기반 탄막 게임의 자동 플레이와 시각 표현을 실험하는 프로젝트입니다.

## 목표

- 재현 가능한 Taisei 원본 빌드와 실행 환경 구축
- 게임 내부 상태 관측과 프레임 단위 자동 입력 연동
- 충돌 예측 기반 회피 기준선 구현
- 최고 난이도 전체 자동 클리어와 리플레이 확보
- 게임 규칙을 유지한 탄막 시각 표현 개선

단기 목표는 한 패턴 또는 한 스테이지의 자동 플레이 시연입니다. 전체 범위는 검증 결과에 따라 단계적으로 확장합니다.

## 현재 상태

Taisei fork를 `game/taisei` Git submodule로 연결하고 Windows x64 원본 빌드와 초기 실행을 확인했습니다. 현재 고정 커밋과 재현 절차는 [로컬 환경 구축 안내](docs/SETUP.md)에 기록되어 있습니다. 게임 상태 관측 및 자동 입력 연동은 아직 구현하지 않았습니다.

## 저장소 구조

| 경로 | 역할 |
| --- | --- |
| `agent/` | 관측 모델, 위험 예측 및 입력 정책 |
| `bridge/` | Taisei와 에이전트 사이의 상태·입력 연동 |
| `configs/` | 실험 설정과 시각 표현 프리셋 |
| `docs/` | 계획, 환경 구축, 구조 분석 및 실험 기록 |
| `game/taisei/` | 사용자 fork를 가리키는 Taisei Git submodule |
| `scripts/` | 설치, 빌드, 실행 및 평가 자동화 |
| `tests/` | 충돌 예측과 연동 등 핵심 동작 검증 |
| `artifacts/` | Git으로 관리 가능한 작은 결과 요약과 리플레이 안내 |

각 디렉터리의 `README.md`에 현재 범위와 추가 원칙을 기록합니다. 구현 언어와 빌드 체계가 확정되면 실제 패키지 구조로 구체화합니다.

## 문서

- [구축 계획](docs/PROJECT_PLAN.md)
- [로컬 환경 구축 안내](docs/SETUP.md)
- [문서 안내](docs/README.md)

## 빠른 시작

Windows PowerShell과 Docker Desktop을 사용합니다.

```powershell
git submodule update --init --recursive
.\scripts\setup-taisei.ps1
.\scripts\build-taisei.ps1
.\scripts\run-taisei.ps1
```

빌드 산출물은 `build/taisei-windows-x64/`에 생성되며 Git에 포함되지 않습니다.

## 원칙

- Taisei 원본 버전과 에이전트 버전을 함께 기록합니다.
- 자동 플레이 결과는 난이도, 캐릭터, 스테이지, 시드 및 규칙 변경 여부와 함께 남깁니다.
- 실시간 조작은 로컬 알고리즘이 수행하며 프레임마다 LLM API를 호출하지 않습니다.
- 대용량 영상, 빌드 산출물, 모델 파일 및 로컬 실행 데이터는 일반 Git 커밋에서 제외합니다.
