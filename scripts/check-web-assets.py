"""Taisei 웹 산출물의 파일 참조·경로·MIME·HTTP 헤더를 검사한다.

사용 예:
    # 1) 정적 검사: 파일 참조와 상대 경로, WASM 형식, data/ 해시 이름만 확인
    python scripts/check-web-assets.py --root build/web/site

    # 2) 정적 + HTTP 검사: 실행 중인 서버에 실제 요청을 보내 상태 코드·MIME·헤더 확인
    python scripts/serve-web.py --root build/web/site --port 8080   # 다른 터미널
    python scripts/check-web-assets.py --root build/web/site --url http://127.0.0.1:8080

    # 3) 리소스 전체 해시 검증(느림) 과 JSON 결과 저장
    python scripts/check-web-assets.py --root build/web/site --verify-hashes --json build/web/check.json

검사 항목:
- 진입 HTML 에서 시작해 script/link/img/a/css url() 참조를 따라가며 로컬 파일 존재 여부를 확인한다.
  대소문자가 다른 참조(Windows 에서는 열리지만 Linux 서버·공개 호스팅에서는 404)도 오류로 잡는다.
- "/..." 절대 경로 참조는 하위 경로 배포를 깨뜨리므로 오류로 보고한다.
- JS 문자열에서 .wasm/.data 참조를 찾아 스크립트 기준 상대 경로로 존재를 확인한다.
- JS 문자열의 .js 참조(셸이 script 요소로 주입하는 로더)는 그 JS 를 실행하는 HTML 문서 기준으로 풀어 따라간다.
  <meta http-equiv="refresh"> 이동 대상도 따라간다. --require-wasm 이면 .wasm 에 도달하지 못할 때 오류로 처리한다.
- .wasm 은 매직 넘버·버전을 확인하고, 공유 메모리(pthreads) 사용 여부로 격리 헤더 필요성을 판정한다.
- Taisei 리소스 디렉터리(기본 data/) 는 파일 이름이 SHA-256 인지, --verify-hashes 면 내용과 일치하는지 확인한다.
- --url 이 있으면 각 리소스를 실제로 요청해 200 응답, Content-Type, Content-Length, 404 동작,
  디렉터리 index 제공, 격리 헤더(필요한 경우에만) 를 확인한다.

종료 코드: 0 오류 없음, 1 오류 있음, 2 사용법 오류(루트·진입 파일 없음 등).
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import posixpath
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from html.parser import HTMLParser
from pathlib import Path

# 파이프로 출력할 때(도구·파일 리다이렉트) 한글이 깨지지 않도록 UTF-8 로 맞춘다. 콘솔 직접 출력은 OS 가 처리한다.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and not _stream.isatty() and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "build" / "web" / "site"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2

# 확장자별로 허용하는 Content-Type(세미콜론 앞 부분). None 이면 검사하지 않는다.
EXPECTED_CONTENT_TYPES: dict[str, set[str] | None] = {
    ".wasm": {"application/wasm"},
    ".js": {"text/javascript", "application/javascript", "application/x-javascript"},
    ".mjs": {"text/javascript", "application/javascript"},
    ".html": {"text/html"},
    ".htm": {"text/html"},
    ".css": {"text/css"},
    ".json": {"application/json"},
    ".webp": {"image/webp"},
    ".png": {"image/png"},
    ".ico": {"image/x-icon", "image/vnd.microsoft.icon"},
    ".txt": {"text/plain"},
}

HTML_REF_ATTRS = {
    "script": ("src",),
    "link": ("href",),
    "img": ("src",),
    "source": ("src", "srcset"),
    "audio": ("src",),
    "video": ("src", "poster"),
    "iframe": ("src",),
    "a": ("href",),
}

CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")
JS_ASSET_RE = re.compile(r"""['"]([A-Za-z0-9_./-]+\.(?:wasm|data|mjs))['"]""")
# 셸이 document.createElement('script') 로 넣는 로더 이름(예: shell-config.js 의 'taisei.js').
# 이런 스크립트 src 는 JS 파일이 아니라 그 JS 를 실행하는 HTML 문서 기준으로 해석된다.
JS_SCRIPT_RE = re.compile(r"""['"`]([A-Za-z0-9_./-]+\.js)['"`]""")
META_REFRESH_URL_RE = re.compile(r"""url\s*=\s*['"]?([^'";]+)""", re.IGNORECASE)
SHA256_NAME_RE = re.compile(r"^[0-9a-f]{64}$")
THREAD_MARKERS = ("SharedArrayBuffer", "PThread", "Atomics.wait")


@dataclass
class Finding:
    level: str  # error | warning | info
    code: str
    message: str
    path: str = ""


@dataclass
class Report:
    root: str
    entry: str
    url: str | None
    findings: list[Finding] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    wasm_files: list[str] = field(default_factory=list)
    threads_required: bool = False
    isolation_required: bool = False
    data_dirs: dict[str, dict] = field(default_factory=dict)
    http_checks: list[dict] = field(default_factory=list)

    def add(self, level: str, code: str, message: str, path: str = "") -> None:
        self.findings.append(Finding(level, code, message, path))

    def error(self, code: str, message: str, path: str = "") -> None:
        self.add("error", code, message, path)

    def warning(self, code: str, message: str, path: str = "") -> None:
        self.add("warning", code, message, path)

    def info(self, code: str, message: str, path: str = "") -> None:
        self.add("info", code, message, path)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]


# ---------------------------------------------------------------------------
# 파일 시스템 보조
# ---------------------------------------------------------------------------

def exists_exact(root: Path, rel: str) -> tuple[bool, bool]:
    """(존재 여부, 대소문자 정확 일치 여부). Windows 의 대소문자 무시를 우회해 실제 이름을 비교한다."""
    current = root
    for part in [p for p in rel.split("/") if p]:
        if not current.is_dir():
            return False, False
        try:
            names = os.listdir(current)
        except OSError:
            return False, False
        if part in names:
            current = current / part
            continue
        lowered = {n.lower(): n for n in names}
        if part.lower() in lowered:
            return True, False
        return False, False
    return current.exists(), True


def is_local_reference(value: str) -> bool:
    value = value.strip()
    if not value or value.startswith("#"):
        return False
    lowered = value.lower()
    if lowered.startswith(("data:", "mailto:", "javascript:", "blob:", "tel:")):
        return False
    parts = urllib.parse.urlsplit(value)
    return not parts.scheme and not parts.netloc


def strip_query(value: str) -> str:
    return value.split("#", 1)[0].split("?", 1)[0].strip()


class RefCollector(HTMLParser):
    """HTML 에서 로컬 리소스 참조를 모은다. 주석 안의 태그는 무시된다."""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str, str]] = []  # (tag, attr, value)
        self.inline_css: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k: (v or "") for k, v in attrs}
        for attr in HTML_REF_ATTRS.get(tag, ()):
            value = attrs_dict.get(attr)
            if not value:
                continue
            if attr == "srcset":
                for candidate in value.split(","):
                    url = candidate.strip().split(" ")[0]
                    if url:
                        self.refs.append((tag, attr, url))
            else:
                self.refs.append((tag, attr, value))
        if tag == "meta" and attrs_dict.get("http-equiv", "").lower() == "refresh":
            # <meta http-equiv="refresh" content="0; url=game/index.html"> 도 이동 경로로 따라간다.
            match = META_REFRESH_URL_RE.search(attrs_dict.get("content", ""))
            if match and match.group(1).strip():
                self.refs.append(("meta", "refresh", match.group(1).strip()))
        style = attrs_dict.get("style")
        if style:
            self.inline_css.append(style)
        if tag == "style":
            self._in_style = True

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.inline_css.append(data)


# ---------------------------------------------------------------------------
# WASM 바이너리 검사
# ---------------------------------------------------------------------------

def _read_leb128(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def inspect_wasm(data: bytes) -> dict:
    """매직·버전 확인과 공유 메모리(pthreads) 플래그 탐지. 파싱 실패는 valid=False 로 돌려준다."""
    info = {"valid": False, "shared_memory": False, "size": len(data), "sections": 0}
    if len(data) < 8 or data[:4] != b"\0asm":
        return info
    if data[4:8] != b"\x01\x00\x00\x00":
        return info
    pos = 8
    try:
        while pos < len(data):
            section_id = data[pos]
            pos += 1
            size, pos = _read_leb128(data, pos)
            body = data[pos:pos + size]
            pos += size
            info["sections"] += 1
            if section_id == 5:  # memory section
                count, p = _read_leb128(body, 0)
                for _ in range(count):
                    flags = body[p]
                    if flags & 0x02:
                        info["shared_memory"] = True
                    p += 1
                    _, p = _read_leb128(body, p)
                    if flags & 0x01:
                        _, p = _read_leb128(body, p)
            elif section_id == 2:  # import section
                count, p = _read_leb128(body, 0)
                for _ in range(count):
                    n, p = _read_leb128(body, p)
                    p += n
                    n, p = _read_leb128(body, p)
                    p += n
                    kind = body[p]
                    p += 1
                    if kind == 0x00:
                        _, p = _read_leb128(body, p)
                    elif kind == 0x01:
                        p += 1
                        flags = body[p]
                        p += 1
                        _, p = _read_leb128(body, p)
                        if flags & 0x01:
                            _, p = _read_leb128(body, p)
                    elif kind == 0x02:
                        flags = body[p]
                        p += 1
                        if flags & 0x02:
                            info["shared_memory"] = True
                        _, p = _read_leb128(body, p)
                        if flags & 0x01:
                            _, p = _read_leb128(body, p)
                    elif kind == 0x03:
                        p += 2
                    elif kind == 0x04:
                        # tag import: attribute + type index
                        p += 1
                        _, p = _read_leb128(body, p)
                    else:
                        raise ValueError(f"unknown import kind {kind}")
        info["valid"] = pos == len(data)
    except (IndexError, ValueError):
        info["valid"] = False
    return info


# ---------------------------------------------------------------------------
# 정적 검사
# ---------------------------------------------------------------------------

def resolve_reference(base_rel: str, value: str) -> tuple[str, bool]:
    """참조 문자열을 루트 기준 posix 상대 경로로 바꾼다. (경로, 절대 경로 참조 여부)"""
    absolute = value.startswith("/")
    if absolute:
        joined = value.lstrip("/")
    else:
        joined = posixpath.join(posixpath.dirname(base_rel), value)
    return posixpath.normpath(joined), absolute


def scan_static(report: Report, root: Path, entry: str, data_dir_name: str, verify_hashes: bool,
                require_wasm: bool = False) -> None:
    queue: list[str] = [entry]
    seen_html: set[str] = set()
    seen_resources: set[str] = set()
    seen_js: set[str] = set()
    wasm_hosts: dict[str, str] = {}  # wasm rel -> 참조한 HTML rel (data/ 위치 기준)

    def register(base_rel: str, value: str, kind: str) -> str | None:
        value = strip_query(value)
        if not value:
            return None
        rel, absolute = resolve_reference(base_rel, value)
        if absolute:
            report.error("absolute-path",
                         f"'{value}' 는 '/' 로 시작하는 절대 경로 참조입니다. 하위 경로 배포에서 깨지므로 상대 경로로 바꿔야 합니다.",
                         base_rel)
        if rel.startswith(".."):
            report.error("escapes-root", f"'{value}' 가 산출물 루트 밖을 가리킵니다.", base_rel)
            return None
        exists, exact = exists_exact(root, rel)
        if not exists:
            report.error("missing-file", f"'{value}' ({kind}) 가 가리키는 파일이 없습니다: {rel}", base_rel)
            return None
        if not exact:
            # 참조는 깨진 것으로 보고 추적을 멈춘다(Linux 에서는 실제로 열 수 없는 경로다).
            report.error("case-mismatch",
                         f"'{value}' 는 실제 파일 이름과 대소문자가 다릅니다. Windows 에서는 열리지만 대소문자를 구분하는 서버에서는 404 가 됩니다.",
                         base_rel)
            return None
        if (root / rel).is_dir():
            return rel
        seen_resources.add(rel)
        return rel

    def scan_css(base_rel: str, css_text: str) -> None:
        for match in CSS_URL_RE.finditer(css_text):
            value = match.group(1)
            if is_local_reference(value):
                register(base_rel, value, "css url()")

    def scan_js(js_rel: str) -> None:
        if js_rel in seen_js:
            return
        seen_js.add(js_rel)
        text = (root / js_rel).read_text(encoding="utf-8", errors="replace")
        markers = [m for m in THREAD_MARKERS if m in text]
        if markers:
            report.threads_required = True
            report.info("threads-markers", f"스레드 관련 식별자 발견: {', '.join(markers)}", js_rel)
        host_html = html_rel_for_js.get(js_rel, entry)
        for match in JS_ASSET_RE.finditer(text):
            value = match.group(1)
            if value.startswith(("http:", "https:")):
                continue
            # Emscripten locateFile 은 스크립트 URL 기준으로 상대 경로를 푼다.
            rel = register(js_rel, value, "JS 문자열")
            if rel and rel.endswith(".wasm"):
                wasm_hosts.setdefault(rel, host_html)
        for match in JS_SCRIPT_RE.finditer(text):
            value = match.group(1)
            if value.startswith(("http:", "https:")):
                continue
            # 동적으로 주입하는 스크립트는 문서 URL 기준으로 풀린다. 문서(host_html) 기준으로 확인하고 따라간다.
            rel = register(host_html, value, f"JS 동적 스크립트 ({js_rel})")
            if rel and not (root / rel).is_dir():
                html_rel_for_js.setdefault(rel, host_html)
                scan_js(rel)

    html_rel_for_js: dict[str, str] = {}

    while queue:
        html_rel = queue.pop(0)
        if html_rel in seen_html:
            continue
        seen_html.add(html_rel)
        html_path = root / html_rel
        text = html_path.read_text(encoding="utf-8", errors="replace")
        collector = RefCollector()
        collector.feed(text)
        for css in collector.inline_css:
            scan_css(html_rel, css)
        for tag, attr, value in collector.refs:
            if not is_local_reference(value):
                continue
            rel = register(html_rel, value, f"<{tag} {attr}>")
            if not rel:
                continue
            lower = rel.lower()
            if (root / rel).is_dir():
                continue
            if lower.endswith((".html", ".htm")) and tag in ("a", "iframe", "link", "meta"):
                queue.append(rel)
            elif lower.endswith((".js", ".mjs")):
                html_rel_for_js.setdefault(rel, html_rel)
                scan_js(rel)
            elif lower.endswith(".css"):
                scan_css(rel, (root / rel).read_text(encoding="utf-8", errors="replace"))
            elif lower.endswith(".wasm"):
                wasm_hosts.setdefault(rel, html_rel)

    report.resources = sorted(seen_resources)

    # WASM 바이너리 검사
    for wasm_rel, host_html in sorted(wasm_hosts.items()):
        data = (root / wasm_rel).read_bytes()
        info = inspect_wasm(data)
        report.wasm_files.append(wasm_rel)
        if not info["valid"]:
            report.error("wasm-invalid", "WASM 매직/버전 또는 섹션 구조가 올바르지 않습니다.", wasm_rel)
            continue
        report.info("wasm-ok", f"유효한 WASM, {info['size']:,} bytes, 섹션 {info['sections']}개", wasm_rel)
        if info["shared_memory"]:
            report.threads_required = True
            report.info("wasm-shared-memory", "공유 메모리(pthreads) 를 사용하는 모듈입니다.", wasm_rel)

        # Taisei 리소스 디렉터리: wasm 안의 "<data_dir>/%s" 문자열로 실제 요청 경로를 확인한다.
        data_marker = f"{data_dir_name}/%s".encode()
        references_data = data_marker in data
        host_dir = posixpath.dirname(host_html)
        data_rel = posixpath.normpath(posixpath.join(host_dir, data_dir_name)) if host_dir else data_dir_name
        data_path = root / data_rel
        if references_data and not data_path.is_dir():
            report.error("data-dir-missing",
                         f"WASM 이 '{data_dir_name}/<id>' 경로를 요청하지만 {data_rel}/ 디렉터리가 없습니다.", wasm_rel)
            continue
        if not references_data:
            if data_path.is_dir():
                report.warning("data-dir-unreferenced",
                               f"{data_rel}/ 가 있지만 WASM 안에 '{data_dir_name}/%s' 문자열이 없습니다. 요청 경로가 다를 수 있습니다.",
                               wasm_rel)
            else:
                report.info("data-dir-none", f"WASM 이 '{data_dir_name}/' 리소스 디렉터리를 참조하지 않습니다.", wasm_rel)
            continue
        entries = sorted(p for p in data_path.iterdir())
        files = [p for p in entries if p.is_file()]
        total = 0
        bad_names = 0
        mismatched = 0
        for p in files:
            total += p.stat().st_size
            if not SHA256_NAME_RE.match(p.name):
                bad_names += 1
                report.error("data-name", "리소스 파일 이름이 64자리 소문자 SHA-256 이 아닙니다.", f"{data_rel}/{p.name}")
                continue
            if verify_hashes:
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
                if digest != p.name:
                    mismatched += 1
                    report.error("data-hash", f"내용의 SHA-256({digest[:12]}…) 이 파일 이름과 다릅니다.", f"{data_rel}/{p.name}")
        subdirs = [p.name for p in entries if p.is_dir()]
        if subdirs:
            report.warning("data-subdirs", f"리소스 디렉터리에 하위 디렉터리가 있습니다: {', '.join(subdirs[:5])}", data_rel)
        report.data_dirs[data_rel] = {
            "files": len(files),
            "bytes": total,
            "bad_names": bad_names,
            "hash_mismatch": mismatched,
            "hashes_verified": verify_hashes,
        }
        verified = " (내용 해시 검증 완료)" if verify_hashes and not mismatched and not bad_names else ""
        report.info("data-dir", f"리소스 {len(files)}개, {total / (1024 * 1024):.1f} MiB{verified}", data_rel)

    if not wasm_hosts:
        message = "진입 페이지에서 도달할 수 있는 .wasm 참조가 없습니다. 진입 파일(--entry) 이 맞는지 확인하세요."
        if require_wasm:
            report.error("no-wasm", message + " (--require-wasm)", entry)
        else:
            report.warning("no-wasm", message, entry)

    report.isolation_required = report.threads_required


# ---------------------------------------------------------------------------
# HTTP 검사
# ---------------------------------------------------------------------------

def http_get(url: str, method: str = "GET", timeout: float = 30.0) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, method=method, headers={"User-Agent": "check-web-assets/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            body = response.read() if method == "GET" else b""
            return response.status, headers, body
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        body = exc.read() if method == "GET" else b""
        return exc.code, headers, body


def content_type_main(headers: dict[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


def scan_live(report: Report, root: Path, base_url: str, entry: str, isolation_mode: str,
              sample_data: int, verify_hashes: bool) -> None:
    base = base_url.rstrip("/")

    def url_for(rel: str) -> str:
        return base + "/" + urllib.parse.quote(rel)

    def record(check: str, rel: str, url: str, status: int, ok: bool, note: str = "",
               headers: dict[str, str] | None = None) -> None:
        report.http_checks.append({
            "check": check,
            "path": rel,
            "url": url,
            "status": status,
            "ok": ok,
            "content_type": (headers or {}).get("content-type", ""),
            "note": note,
        })

    def fetch(check: str, rel: str, url: str) -> tuple[int, dict[str, str], bytes] | None:
        """요청 실패(연결 거부·끊김·잘못된 응답)를 traceback 대신 finding 으로 남긴다."""
        try:
            return http_get(url)
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            report.error("http-error", f"요청 실패 {url}: {exc}", rel)
            record(check, rel, url, 0, False, f"요청 실패: {exc}")
            return None

    # 서버 연결 확인
    try:
        http_get(base + "/")
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        report.error("server-unreachable", f"{base}/ 에 연결할 수 없습니다: {exc}")
        record("server", "", base + "/", 0, False, str(exc))
        return

    def expect_file(check: str, rel: str, expected_types: set[str] | None, verify_hash: bool = False) -> bool:
        """rel 이 200·기대 MIME·파일과 같은 길이로 제공되는지 확인하고 결과를 기록한다."""
        url = url_for(rel)
        file_path = root / rel
        if not file_path.is_file():
            report.error("resource-missing", "정적 검사 단계에서 사라진 파일입니다.", rel)
            record(check, rel, url, 0, False, "파일 없음")
            return False
        response = fetch(check, rel, url)
        if response is None:
            return False
        status, headers, body = response
        problems: list[str] = []
        if status != 200:
            problems.append(f"status {status}")
        actual = content_type_main(headers)
        if expected_types is not None and actual not in expected_types:
            problems.append(f"Content-Type '{actual or '없음'}' (기대: {' 또는 '.join(sorted(expected_types))})")
        elif expected_types is None and actual == "text/html":
            problems.append("Content-Type 이 text/html (SPA fallback 등으로 잘못된 내용이 전달됨)")
        size = file_path.stat().st_size
        if status == 200 and len(body) != size:
            problems.append(f"본문 {len(body)} bytes ≠ 파일 {size} bytes")
        if status == 200 and verify_hash and hashlib.sha256(body).hexdigest() != file_path.name:
            problems.append("응답 본문 SHA-256 이 파일 이름과 다릅니다")
        record(check, rel, url, status, not problems, "; ".join(problems), headers)
        if problems:
            report.error(f"{check}-http", "; ".join(problems), rel)
        return not problems

    # 0) 진입 HTML 자체: 참조 목록에는 없으므로 따로 200·text/html·본문 길이를 확인한다.
    if expect_file("entry", entry, EXPECTED_CONTENT_TYPES[".html"]):
        report.info("entry-http", f"{url_for(entry)} → 200 text/html 확인", entry)

    # 1) 진입 디렉터리의 index 제공
    entry_dir = posixpath.dirname(entry)
    entry_dir_url = base + "/" + (urllib.parse.quote(entry_dir) + "/" if entry_dir else "")
    index_exists = (root / entry_dir / "index.html").is_file()
    response = fetch("directory-index", entry_dir + "/", entry_dir_url)
    if response is not None:
        status, headers, body = response
        if index_exists:
            ok = status == 200 and content_type_main(headers) == "text/html"
            record("directory-index", entry_dir + "/", entry_dir_url, status, ok, headers=headers)
            if not ok:
                report.error("directory-index",
                             f"{entry_dir_url} 가 index.html 을 text/html 로 돌려주지 않습니다"
                             f"(status {status}, {content_type_main(headers) or '없음'}).")
            else:
                report.info("directory-index", f"{entry_dir_url} → index.html 제공 확인")
        else:
            ok = status != 200
            record("directory-no-listing", entry_dir + "/", entry_dir_url, status, ok, headers=headers)
            if not ok:
                report.warning("directory-listing",
                               f"{entry_dir_url} 에 index.html 이 없는데 200 을 돌려줍니다(디렉터리 목록 노출 가능).")

    # 2) 모든 참조 리소스
    for rel in report.resources:
        ext = posixpath.splitext(rel)[1].lower()
        expect_file("resource", rel, EXPECTED_CONTENT_TYPES.get(ext))

    # 3) 리소스 디렉터리 표본(또는 전체): 확장자 없는 파일이 그대로 전달되는지
    for data_rel, stats in report.data_dirs.items():
        files = sorted(p for p in (root / data_rel).iterdir() if p.is_file())
        chosen = files if sample_data < 0 else files[:sample_data]
        for p in chosen:
            expect_file("data", f"{data_rel}/{p.name}", None, verify_hash=verify_hashes)
        label = "전체" if sample_data < 0 else f"표본 {len(chosen)}개"
        report.info("data-http", f"{data_rel}/ 리소스 {label} 요청 확인", data_rel)

    # 4) 404 동작: 없는 경로와 없는 .wasm 은 반드시 404 여야 한다(HTML fallback 금지).
    token = secrets.token_hex(6)
    for probe in (f"__check_missing_{token}", f"__check_missing_{token}.wasm"):
        rel = posixpath.join(entry_dir, probe) if entry_dir else probe
        url = url_for(rel)
        response = fetch("not-found", rel, url)
        if response is None:
            continue
        status, headers, body = response
        ok = status == 404
        record("not-found", rel, url, status, ok, headers=headers)
        if not ok:
            report.error("not-found", f"없는 경로 {rel} 에 404 대신 {status} 를 돌려줍니다.")
    report.info("not-found", "없는 경로와 없는 .wasm 에 404 응답 확인")

    # 5) 격리 헤더(COOP/COEP): 스레드 빌드에만 필요하다.
    if isolation_mode == "auto":
        required = report.threads_required
    else:
        required = isolation_mode == "yes"
    report.isolation_required = required
    response = fetch("isolation", entry, url_for(entry))
    if response is None:
        return
    status, headers, body = response
    coop = headers.get("cross-origin-opener-policy", "")
    coep = headers.get("cross-origin-embedder-policy", "")
    isolated = coop == "same-origin" and coep in ("require-corp", "credentialless")
    record("isolation", entry, url_for(entry), status, (not required) or isolated,
           f"COOP={coop or '없음'}, COEP={coep or '없음'}", headers)
    if required and not isolated:
        report.error("isolation-missing",
                     f"스레드(SharedArrayBuffer) 빌드에는 COOP: same-origin, COEP: require-corp 가 필요하지만 "
                     f"COOP={coop or '없음'}, COEP={coep or '없음'} 입니다.", entry)
    elif required:
        report.info("isolation-ok", f"격리 헤더 확인 COOP={coop}, COEP={coep}", entry)
    elif isolated:
        report.info("isolation-present", f"격리 헤더가 켜져 있습니다(이 빌드에는 필요하지 않음) COOP={coop}, COEP={coep}", entry)
    else:
        report.info("isolation-unneeded", "스레드를 쓰지 않는 빌드이므로 COOP/COEP 격리 헤더는 필요하지 않습니다.", entry)

    cache = headers.get("cache-control", "")
    report.info("cache-control", f"Cache-Control: {cache or '없음'}", entry)
    nosniff = headers.get("x-content-type-options", "")
    if nosniff:
        report.info("nosniff", f"X-Content-Type-Options: {nosniff}", entry)


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------

def print_report(report: Report) -> None:
    print(f"루트: {report.root}")
    print(f"진입: {report.entry}")
    if report.url:
        print(f"서버: {report.url}")
    print(f"참조 리소스: {len(report.resources)}개, WASM: {', '.join(report.wasm_files) or '없음'}")
    print(f"스레드(pthreads) 요구: {'예' if report.threads_required else '아니오'} → "
          f"COOP/COEP 격리 헤더 {'필요' if report.isolation_required else '불필요'}")
    for data_rel, stats in report.data_dirs.items():
        print(f"리소스 디렉터리 {data_rel}/: {stats['files']}개, {stats['bytes'] / (1024 * 1024):.1f} MiB, "
              f"해시 검증 {'완료' if stats['hashes_verified'] else '생략'}")
    print()
    for level, label in (("error", "오류"), ("warning", "경고"), ("info", "정보")):
        items = [f for f in report.findings if f.level == level]
        if not items:
            continue
        print(f"[{label} {len(items)}건]")
        for f in items:
            where = f" ({f.path})" if f.path else ""
            print(f"  - {f.code}{where}: {f.message}")
    print()
    if report.url:
        failed = [c for c in report.http_checks if not c["ok"]]
        print(f"HTTP 검사: {len(report.http_checks)}건 중 실패 {len(failed)}건")
    status = "실패" if report.errors else "통과"
    print(f"결과: {status} (오류 {len(report.errors)}, 경고 {len(report.warnings)})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Taisei 웹 산출물의 파일 참조·경로·MIME·HTTP 헤더를 검사한다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="종료 코드: 0 오류 없음, 1 오류 있음, 2 사용법 오류.",
    )
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help=f"산출물 디렉터리 (기본: {DEFAULT_ROOT.relative_to(REPO_ROOT).as_posix()})")
    parser.add_argument("--entry", default="index.html", help="루트 기준 진입 HTML (기본: index.html)")
    parser.add_argument("--url", help="실행 중인 서버 주소. 지정하면 HTTP 검사를 수행 (예: http://127.0.0.1:8080)")
    parser.add_argument("--data-dir", default="data", help="Taisei 리소스 디렉터리 이름 (기본: data)")
    parser.add_argument("--verify-hashes", action="store_true", help="리소스 파일 내용의 SHA-256 을 이름과 대조(느림)")
    parser.add_argument("--sample-data", type=int, default=3,
                        help="HTTP 검사에서 요청할 리소스 파일 수 (기본: 3, -1 이면 전체)")
    parser.add_argument("--require-isolation", choices=("auto", "yes", "no"), default="auto",
                        help="COOP/COEP 요구 여부. auto 는 스레드 사용이 감지될 때만 요구 (기본: auto)")
    parser.add_argument("--require-wasm", action="store_true",
                        help="진입 페이지에서 .wasm 에 도달하지 못하면 경고 대신 오류로 처리(게임 산출물 검증용)")
    parser.add_argument("--json", help="결과를 JSON 파일로 저장")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    entry = args.entry.replace("\\", "/").strip("/")
    if not root.is_dir():
        print(f"check-web-assets: 루트 디렉터리가 없습니다: {root}", file=sys.stderr)
        return EXIT_USAGE
    if not (root / entry).is_file():
        print(f"check-web-assets: 진입 파일이 없습니다: {root / entry} (--entry 로 지정)", file=sys.stderr)
        return EXIT_USAGE

    report = Report(root=str(root), entry=entry, url=args.url)
    scan_static(report, root, entry, args.data_dir, args.verify_hashes, require_wasm=args.require_wasm)
    if args.url:
        scan_live(report, root, args.url, entry, args.require_isolation, args.sample_data, args.verify_hashes)

    print_report(report)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(report)
        payload["errors"] = len(report.errors)
        payload["warnings"] = len(report.warnings)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 저장: {out}")
    return EXIT_FINDINGS if report.errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
