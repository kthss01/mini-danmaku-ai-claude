# Tests

충돌 예측, 이동 후보 평가, 관측 직렬화 및 입력 동기화의 자동 검증을 둡니다.

현재 있는 웹 관련 검증:

- `web-server/`: 로컬 서버·자산 검사 도구의 fixture 기반 unittest
- `web-shell/`: 웹 셸 mock 로더와 검증 사이트 구성 스크립트
- `web-play/`: 브라우저 플레이 QA 증거 양식과 검증 기록([docs/web/QA.md](../docs/web/QA.md))

테스트 도구와 디렉터리 세분화는 구현 언어 및 브리지 설계를 확정한 뒤 정합니다.
