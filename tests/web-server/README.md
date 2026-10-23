# 웹 서버·리소스 검사 테스트

`scripts/serve-web.py` 와 `scripts/check-web-assets.py` 를 작은 fixture 로 검증한다. 실제 게임 산출물 검증은 [docs/web/SERVING.md](../../docs/web/SERVING.md) 의 절차를 따른다.

```bash
python -m unittest discover -s tests/web-server -t tests/web-server -v
```

- `make_fixture.py`: `fixture/site` 를 생성한다. 진입 `index.html`, `game/` 하위 HTML·JS·최소 WASM, 해시 이름 리소스 `game/data/` 로 실제 산출물 구조를 흉내 낸다.
- `test_serve_web.py`: index 제공, WASM/JS MIME, 상대 경로, 404, 캐시·격리 헤더, 디렉터리 목록 차단, 경로 탈출 방지(인코딩 역슬래시·중첩 상위 경로·루트 밖 symlink; symlink 권한이 없는 환경은 해당 테스트만 skip), 포트 충돌·경로 부재 종료 코드, 문서 명령 그대로의 실행·종료.
- `test_check_web_assets.py`: 참조 수집, 대소문자 불일치·절대 경로·누락 파일·해시 불일치 검출, 스레드 빌드 감지와 COOP/COEP 요구 판정, 잘못된 MIME·HTML fallback·진입 HTML 404·응답 없이 끊는 서버 검출(traceback 없이 종료 코드 1). 동적 주입 로더 추적(문서 기준 해석)·meta refresh·`--require-wasm`.

Linux 에서도 같은 명령으로 실행해야 한다(대소문자·symlink 동작이 Windows 와 다르다). Docker 가 있으면:

```bash
docker run --rm -v "$(pwd):/work" -w /work python:3.12-slim python -m unittest discover -s tests/web-server -t tests/web-server -v
```

fixture 를 바꾸면 `python tests/web-server/make_fixture.py` 로 다시 생성한다. 커밋된 fixture 와 생성기가 어긋나면 테스트가 실패한다.
