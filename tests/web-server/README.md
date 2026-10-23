# 웹 서버·리소스 검사 테스트

`scripts/serve-web.py` 와 `scripts/check-web-assets.py` 를 작은 fixture 로 검증한다. 실제 게임 산출물 검증은 [docs/web/SERVING.md](../../docs/web/SERVING.md) 의 절차를 따른다.

```bash
python -m unittest discover -s tests/web-server -t tests/web-server -v
```

- `make_fixture.py`: `fixture/site` 를 생성한다. 진입 `index.html`, `game/` 하위 HTML·JS·최소 WASM, 해시 이름 리소스 `game/data/` 로 실제 산출물 구조를 흉내 낸다.
- `test_serve_web.py`: index 제공, WASM/JS MIME, 상대 경로, 404, 캐시·격리 헤더, 디렉터리 목록 차단, 경로 탈출 방지, 포트 충돌·경로 부재 종료 코드, 문서 명령 그대로의 실행·종료.
- `test_check_web_assets.py`: 참조 수집, 대소문자 불일치·절대 경로·누락 파일·해시 불일치 검출, 스레드 빌드 감지와 COOP/COEP 요구 판정, 잘못된 MIME·HTML fallback 서버 검출.

fixture 를 바꾸면 `python tests/web-server/make_fixture.py` 로 다시 생성한다. 커밋된 fixture 와 생성기가 어긋나면 테스트가 실패한다.
