# Scripts

설치, 빌드, 실행, 반복 실험 및 평가를 재현하는 스크립트를 둡니다.

- `setup-taisei.ps1`: 하위 모듈 초기화와 fork/upstream 원격 검증
- `build-taisei.ps1`: 공식 CI 컨테이너로 현재 고정 커밋의 Windows x64 빌드 생성
- `run-taisei.ps1`: 격리된 로컬 저장 경로로 빌드 결과 실행

스크립트는 실패 시 오류를 반환하고, 사용자별 경로나 인증 정보를 포함하지 않습니다.
