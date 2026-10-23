"""테스트 공통 보조: 하이픈이 든 스크립트 파일을 모듈로 불러오고 임시 서버를 띄운다."""

from __future__ import annotations

import importlib.util
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE_SITE = TESTS_DIR / "fixture" / "site"


def load_script(name: str) -> ModuleType:
    """scripts/<name>.py 를 모듈로 읽는다(파일 이름에 '-' 가 있어 import 문으로는 불러올 수 없다)."""
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclass 가 모듈 네임스페이스를 찾을 수 있도록 실행 전에 등록한다.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


serve_web = load_script("serve-web")
check_web_assets = load_script("check-web-assets")


class LiveServer:
    """serve-web 의 서버를 백그라운드 스레드로 띄우는 컨텍스트 매니저. 포트는 자동 선택한다."""

    def __init__(self, root: Path, **kwargs):
        self.root = root
        self.kwargs = kwargs
        self.server = None
        self.thread = None
        self.url = ""

    def __enter__(self) -> "LiveServer":
        self.server = serve_web.create_server(self.root, host="127.0.0.1", port=0, quiet=True, **self.kwargs)
        host, port = self.server.server_address[:2]
        self.url = f"http://{host}:{port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        assert self.server
        self.server.shutdown()
        self.server.server_close()

    def get(self, path: str, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
        request = urllib.request.Request(self.url + path, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
