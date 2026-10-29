"""에피소드 하나를 구동한다: 브라우저·페이지 기동 → 시작 신호 → 종료·한도 감시 → 수집 → 정리.

정책은 페이지 안에서 돈다. 이 모듈은 호스트 API(window.taiseiAI)로 시작·정지하고 이벤트를 모을 뿐이다.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .browser import Browser, BrowserError
from .cdp import CdpConnection, CdpError, wait_until
from .config import RunConfig
from .runfiles import RunDir, RunLogger, utc_now

POLL_INTERVAL_S = 0.25
EVENT_CAP = 200_000
ENDED_STATES = ("exited", "error", "unsupported")
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# 페이지가 만들어지기 전에 심는 스크립트. 실행 설정을 window.taiseiAIRun으로 넘기고 이벤트를 모은다.
_INIT_SCRIPT = r"""
(function () {
  var run = %RUN_JSON%;
  window.taiseiAIRun = run;
  var r = window.__taiseiRunner = { events: [], dropped: 0, hooked: false, pageErrors: [] };
  r.hook = function () {
    if (r.hooked) return true;
    var ai = window.taiseiAI;
    if (!ai || typeof ai.onEvent !== 'function') return false;
    ai.onEvent(function (e) {
      if (r.events.length >= %EVENT_CAP%) { r.dropped++; return; }
      try { r.events.push(JSON.parse(JSON.stringify(e))); }
      catch (x) { r.events.push({ type: 'unserializable_event' }); }
    });
    r.hooked = true;
    return true;
  };
  r.drain = function () { var e = r.events; r.events = []; return e; };
  window.addEventListener('error', function (e) { r.pageErrors.push(String(e.message || e)); });
})();
"""

_POLL_EXPRESSION = r"""
(function () {
  var out = { shell: null, ai: null, events: [], dropped: 0, hooked: false, bridge: false, aiError: null };
  var s = window.taiseiShell;
  if (s) {
    var d = document.getElementById('error-detail');
    var m = document.getElementById('error-message');
    out.shell = { state: s.state, hadFirstFrame: !!s.hadFirstFrame,
                  error: m ? (m.textContent || '').trim() : '', errorDetail: d ? (d.textContent || '').trim() : '' };
  }
  var r = window.__taiseiRunner;
  if (r) { out.hooked = r.hook(); out.events = r.drain(); out.dropped = r.dropped; }
  var ai = window.taiseiAI;
  out.bridge = !!(ai && typeof ai.state === 'function');
  if (out.bridge) {
    try { out.ai = JSON.parse(JSON.stringify(ai.state())); } catch (x) { out.aiError = String(x); }
  }
  return out;
})()
"""


# 브리지 계약(docs/ai/CONTRACT.md 4절)의 소유권 상태·전환 사유. state()는 이름 또는 정수 코드를 줄 수 있다.
OWNER_STATES = {0: "manual", 1: "ai_active", 2: "ai_suspended"}
OWNER_REASONS = ["none", "pause", "focus_lost", "dialog", "stage_end", "restart", "host_request", "user_input",
                 "policy_error", "policy_deadline", "observation_invalid", "bridge_error", "game_over", "not_playing"]
# 이벤트 이름 → 전환 후 소유권 상태
_EVENT_OWNER = {"ai_enable": "ai_active", "ai_resume": "ai_active", "ai_suspend": "ai_suspended", "ai_disable": "manual"}
# 호스트 API(PR #42)의 {type: 'transition', ...} 이벤트는 전환 후 상태를 state·mode·to 중 하나로 싣는다고 가정한다.
# (소유권 상태, 사유) → (run.status, run.reason). 이벤트(episode_end) 없이도 브리지 상태만으로 끝을 안다.
DERIVED_END = {
    ("ai_suspended", "stage_end"): ("completed", "stage_end"),
    ("ai_suspended", "game_over"): ("completed", "game_over"),
    ("ai_suspended", "restart"): ("aborted", "user_abort"),
    ("ai_suspended", "not_playing"): ("error", "runner_error"),
    ("manual", "user_input"): ("aborted", "user_abort"),
    ("manual", "policy_error"): ("error", "policy_error"),
    ("manual", "observation_invalid"): ("error", "observation_invalid"),
    ("manual", "bridge_error"): ("error", "runner_error"),
}


def normalize_owner_state(value) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return OWNER_STATES.get(value)
    return value if value in OWNER_STATES.values() else None


def normalize_owner_reason(value) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return OWNER_REASONS[value] if 0 <= value < len(OWNER_REASONS) else None
    return value if value in OWNER_REASONS else None


def _first(state: dict, *keys):
    for key in keys:
        if key in state and state[key] is not None:
            return state[key]
    return None


def owner_of(state: dict | None) -> str | None:
    """어댑터의 owner_state(이름·정수) 또는 호스트 API의 mode."""
    return normalize_owner_state(_first(state, "owner_state", "mode")) if isinstance(state, dict) else None


def reason_of(state: dict | None) -> str | None:
    """어댑터의 owner_reason 또는 호스트 API의 reason."""
    return normalize_owner_reason(_first(state, "owner_reason", "reason")) if isinstance(state, dict) else None


def state_frame(state: dict | None):
    if not isinstance(state, dict):
        return None
    frame = _first(state, "frame", "last_frame", "lastFrame")
    return frame if isinstance(frame, int) and not isinstance(frame, bool) else None


def state_episode_id(state: dict | None):
    if not isinstance(state, dict):
        return None
    value = _first(state, "episode_id", "episodeId")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass
class EpisodeResult:
    """에피소드 하나의 실행 사실. 에피소드 파일의 run·runner 블록이 된다."""

    index: int
    started_at: str = ""
    ended_at: str = ""
    status: str = "error"
    reason: str = "runner_error"
    detail: str = ""
    evaluable: bool = False
    startup_failed: bool = False
    interrupted: bool = False
    bridge_present: bool = False
    startup_s: float | None = None
    running_s: float | None = None
    events: list = field(default_factory=list)
    first_state: dict | None = None
    last_state: dict | None = None
    shell_final: dict | None = None
    console_errors: int = 0
    dropped_events: int = 0
    input_release: dict = field(default_factory=lambda: {"released": None, "detail": "not_checked"})
    cleanup: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    artifacts: list = field(default_factory=list)
    shell_states: list = field(default_factory=list)
    owner_transitions: list = field(default_factory=list)
    browser_version: str = ""
    enable_frame: int | None = None          # enable 직후 첫 샘플의 프레임
    pre_enable_frame: int | None = None      # enable 직전 마지막 샘플의 프레임(한도 기준)
    end_frame: int | None = None             # 마지막으로 본 프레임
    evidence_errors: list = field(default_factory=list)   # 증거 수집·저장 중 실패(정리 판정과 별개로 보존)
    cleanup_errors: list = field(default_factory=list)    # 정리 단계 예외(입력 해제 확인·브라우저 종료)
    t_enable: float | None = None


class EpisodeDriver:
    def __init__(self, cfg: RunConfig, run_dir: RunDir, logger: RunLogger, server_url: str, entry: str,
                 executable: str, run_id: str):
        self.cfg = cfg
        self.run_dir = run_dir
        self.logger = logger
        self.url = server_url + entry
        self.executable = executable
        self.run_id = run_id
        self._console_file = open(run_dir.logs / "browser-console.log", "a", encoding="utf-8")
        self._game_file = open(run_dir.logs / "game.log", "a", encoding="utf-8")

    def close(self) -> None:
        self._console_file.close()
        self._game_file.close()

    # ---- 페이지 설정 ----
    def _run_settings(self, index: int) -> dict:
        cfg = self.cfg
        return {
            "run_id": self.run_id,
            "experiment_id": cfg.experiment_id,
            "episode_index": index,
            "episodes_total": cfg.episodes,
            "mode": cfg.mode,
            "scenario": cfg.scenario(),
            "policy": {"name": cfg.policy, "version": cfg.policy_version, "params": cfg.policy_params},
            "limits": {"max_frames": cfg.max_frames, "wall_timeout_s": cfg.wall_timeout_s},
            "game_args": cfg.game_args(),
            "shot_inverted": cfg.shot_inverted,
        }

    def _install_page_hooks(self, conn: CdpConnection, index: int) -> None:
        conn.call("Page.enable")
        conn.call("Runtime.enable")
        conn.call("Log.enable")
        source = (_INIT_SCRIPT.replace("%RUN_JSON%", json.dumps(self._run_settings(index)))
                  .replace("%EVENT_CAP%", str(EVENT_CAP)))
        conn.call("Page.addScriptToEvaluateOnNewDocument", {"source": source})

    # ---- 콘솔 수집 ----
    def _pump_console(self, conn: CdpConnection, index: int, result: EpisodeResult) -> None:
        for event in conn.drain_events():
            method = event.get("method")
            params = event.get("params", {})
            if method == "Runtime.consoleAPICalled":
                text = " ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", []))
                level = params.get("type", "log")
                self._console_file.write(f"[ep{index:04d}] {level}: {text}\n")
                if level == "error":
                    result.console_errors += 1
            elif method == "Runtime.exceptionThrown":
                detail = params.get("exceptionDetails", {})
                text = (detail.get("exception") or {}).get("description") or detail.get("text", "")
                self._console_file.write(f"[ep{index:04d}] exception: {text}\n")
                result.console_errors += 1
            elif method == "Log.entryAdded":
                entry = params.get("entry", {})
                self._console_file.write(f"[ep{index:04d}] {entry.get('level')}: {entry.get('text')} {entry.get('url', '')}\n")
                if entry.get("level") == "error":
                    result.console_errors += 1
            elif method in ("Inspector.targetCrashed", "Target.targetCrashed"):
                self._console_file.write(f"[ep{index:04d}] CRASH: {method}\n")
                result.detail = result.detail or "페이지 프로세스가 비정상 종료했습니다"
        self._console_file.flush()

    def _poll(self, conn: CdpConnection, index: int, result: EpisodeResult) -> dict:
        self._pump_console(conn, index, result)
        data = conn.evaluate(_POLL_EXPRESSION, timeout=15)
        if data.get("shell"):
            state = data["shell"]["state"]
            if not result.shell_states or result.shell_states[-1] != state:
                result.shell_states.append(state)
            result.shell_final = data["shell"]
        if data.get("ai") is not None:
            result.last_state = data["ai"]
            frame_now = state_frame(data["ai"])
            if frame_now is not None:
                result.end_frame = frame_now
            if result.first_state is None:
                result.first_state = data["ai"]
        result.dropped_events = max(result.dropped_events, data.get("dropped", 0))
        self._absorb_events(data.get("events", []), index, result)
        return data

    def _absorb_events(self, events: list, index: int, result: EpisodeResult) -> None:
        for event in events:
            if isinstance(event, dict) and event.get("type") == "artifact":
                self._save_artifact(event, index, result)
            if isinstance(event, dict):
                owner = _EVENT_OWNER.get(event.get("type"))
                if event.get("type") == "transition":
                    owner = normalize_owner_state(_first(event, "state", "mode", "to"))
                if owner is not None:
                    reason = normalize_owner_reason(event.get("reason")) or "none"
                    self._record_owner(result, owner, reason, _first(event, "frame", "lastFrame"))
            result.events.append(event)

    def _record_owner(self, result: EpisodeResult, owner: str, reason: str, frame) -> None:
        """소유권 전환을 기록한다. 직전과 같은 (상태, 사유)는 건너뛴다."""
        last = result.owner_transitions[-1] if result.owner_transitions else None
        if last and last["state"] == owner and last["reason"] == reason:
            return
        wall_ms = None if result.t_enable is None else round((time.monotonic() - result.t_enable) * 1000, 1)
        result.owner_transitions.append({"frame": frame if isinstance(frame, int) else None, "wall_ms": wall_ms,
                                         "state": owner, "reason": reason})

    def _save_artifact(self, event: dict, index: int, result: EpisodeResult) -> None:
        """트레이스·리플레이 같은 큰 데이터는 artifact 이벤트(이름·인코딩·조각)로 받아 파일로 저장한다."""
        name = str(event.get("name", ""))
        if not _NAME_PATTERN.match(name):
            self.logger.log(f"artifact 이름이 올바르지 않아 건너뜁니다: {name!r}", "WARN")
            return
        data = event.get("data", "")
        try:
            payload = base64.b64decode(data) if event.get("encoding") == "base64" else str(data).encode("utf-8")
        except (ValueError, TypeError):
            self.logger.log(f"artifact {name} 디코딩 실패", "WARN")
            return
        rel = f"episodes/{index:04d}/{name}"
        try:
            target = self.run_dir.episode_extra_dir(index) / name
            with open(target, "ab") as handle:
                handle.write(payload)
        except OSError as exc:
            # 증거 저장 실패가 실행·정리를 막지 않게 하고, 실패 사실은 에피소드 기록에 남긴다.
            result.evidence_errors.append(f"artifact {name} 저장 실패: {exc!r}")
            self.logger.log(f"episode {index}: artifact {name} 저장 실패: {exc!r}", "WARN")
            return
        if rel not in result.artifacts:
            result.artifacts.append(rel)

    # ---- 본 흐름 ----
    def run(self, index: int) -> EpisodeResult:
        cfg = self.cfg
        result = EpisodeResult(index=index, started_at=utc_now())
        browser = Browser(self.executable, cfg.headless)
        t0 = time.monotonic()
        conn: CdpConnection | None = None
        try:
            try:
                browser.launch()
            except BrowserError as exc:
                result.detail = f"브라우저 기동 실패: {exc}"
                result.startup_failed = True
                return result
            conn = browser.conn
            assert conn is not None
            result.browser_version = browser.version
            self._install_page_hooks(conn, index)
            self.logger.log(f"episode {index}: 브라우저 {browser.version} (포트 {browser.port}), 이동 {self.url}")
            conn.call("Page.navigate", {"url": self.url})
            if not self._reach_playing(conn, index, result, t0):
                result.startup_failed = True
                return result
            result.startup_s = round(time.monotonic() - t0, 3)
            if cfg.mode == "smoke":
                self._smoke(conn, index, result)
            else:
                self._bridge_episode(conn, index, result)
        except CdpError as exc:
            result.status, result.reason = "error", "runner_error"
            result.detail = result.detail or f"브라우저 제어 오류: {exc}"
            result.startup_failed = result.startup_failed or result.startup_s is None
        except KeyboardInterrupt:
            # 정리(_finish)까지 마친 뒤 호출자가 종료 코드 130으로 끝내도록 표시만 하고 되던져지지 않는다.
            result.status, result.reason, result.detail = "aborted", "user_abort", "사용자 중단(Ctrl+C)"
            result.interrupted = True
        finally:
            self._finish(conn, browser, index, result)
        return result

    def _reach_playing(self, conn: CdpConnection, index: int, result: EpisodeResult, t0: float) -> bool:
        cfg = self.cfg
        deadline = time.monotonic() + cfg.startup_timeout_s
        clicked = False
        while time.monotonic() < deadline:
            if conn.closed.is_set():
                result.detail = f"시작 중 브라우저 연결이 끊겼습니다: {conn.close_reason}"
                return False
            try:
                data = self._poll(conn, index, result)
            except CdpError as exc:
                # 이동 직후에는 평가 컨텍스트가 바뀌어 일시적으로 실패할 수 있다.
                if time.monotonic() > deadline - 1:
                    result.detail = f"시작 중 페이지 평가 실패: {exc}"
                    return False
                time.sleep(POLL_INTERVAL_S)
                continue
            shell = data.get("shell") or {}
            state = shell.get("state")
            if state == "playing":
                return True
            if state in ("error", "unsupported", "exited"):
                result.detail = f"셸이 {state} 상태입니다: {shell.get('error', '')} {shell.get('errorDetail', '')}".strip()
                return False
            if state == "ready" and not clicked:
                clicked = self._click_start(conn)
            time.sleep(POLL_INTERVAL_S)
        result.detail = f"{cfg.startup_timeout_s}초 안에 playing 상태에 이르지 못했습니다(마지막 셸 상태: {result.shell_states[-1:] or '없음'})"
        return False

    def _click_start(self, conn: CdpConnection) -> bool:
        """시작 버튼을 실제 마우스 입력으로 누른다(오디오·전체 화면 등 사용자 제스처가 필요한 기능 대비)."""
        rect = conn.evaluate(
            "(function(){var b=document.getElementById('start');if(!b)return null;"
            "var r=b.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2,w:r.width};})()")
        if not rect or not rect.get("w"):
            return False
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            conn.call("Input.dispatchMouseEvent", {"type": kind, "x": rect["x"], "y": rect["y"],
                                                   "button": "left", "clickCount": 1})
        return True

    def _smoke(self, conn: CdpConnection, index: int, result: EpisodeResult) -> None:
        """브리지 없이 셸이 playing을 유지하는지만 지켜본다. 평가 대상이 아니다(evaluable=false)."""
        cfg = self.cfg
        t1 = time.monotonic()
        end = t1 + cfg.smoke_duration_s
        while time.monotonic() < end:
            if conn.closed.is_set():
                result.status, result.reason = "error", "runner_error"
                result.detail = f"관찰 중 브라우저 연결이 끊겼습니다: {conn.close_reason}"
                break
            data = self._poll(conn, index, result)
            state = (data.get("shell") or {}).get("state")
            result.bridge_present = bool(data.get("bridge"))
            if state != "playing":
                result.status, result.reason = "error", "runner_error"
                result.detail = f"관찰 중 셸 상태가 {state}로 바뀌었습니다: {(data.get('shell') or {}).get('error', '')}"
                break
            time.sleep(POLL_INTERVAL_S)
        else:
            result.status, result.reason = "completed", "smoke_duration"
            result.detail = f"playing 상태로 {cfg.smoke_duration_s}초 유지(브리지 없이 셸만 확인)"
        result.evaluable = False
        result.running_s = round(time.monotonic() - t1, 3)

    def _bridge_episode(self, conn: CdpConnection, index: int, result: EpisodeResult) -> None:
        cfg = self.cfg
        # 브리지가 나타날 때까지 기다린다. 끝내 없으면 실험을 시작할 수 없다.
        ready = wait_until(lambda: self._bridge_ready(conn, index, result), timeout=min(30.0, cfg.startup_timeout_s))
        if ready:
            # 호스트 API의 ready Promise(브리지 연결·빌드 정보 확인이 끝나는 시점)를 기다린다. 없으면 건너뛴다.
            try:
                conn.evaluate("(window.taiseiAI.ready && typeof window.taiseiAI.ready.then === 'function')"
                              " ? window.taiseiAI.ready.then(function () { return true; }) : true",
                              await_promise=True, timeout=cfg.startup_timeout_s)
            except CdpError as exc:
                result.status, result.reason = "error", "runner_error"
                result.detail = f"taiseiAI.ready가 실패했습니다: {exc}"
                result.startup_failed = True
                return
        if not ready:
            result.status, result.reason = "error", "runner_error"
            result.detail = "bridge_missing: window.taiseiAI가 없거나 준비되지 않았습니다(브리지가 이 빌드에 없음)"
            result.startup_failed = True
            return
        result.bridge_present = True
        t1 = time.monotonic()
        options = {"episode_index": index, "scenario": cfg.scenario(),
                   "policy": {"name": cfg.policy, "version": cfg.policy_version, "params": cfg.policy_params},
                   "limits": {"max_frames": cfg.max_frames}}
        if cfg.policy != "none" and self._has_method(conn, "loadPolicy"):
            try:
                conn.evaluate(f"window.taiseiAI.loadPolicy({json.dumps(cfg.policy)}, {json.dumps(cfg.policy_params)})",
                              await_promise=True, timeout=30)
            except CdpError as exc:
                result.status, result.reason = "error", "policy_error"
                result.detail = f"정책 {cfg.policy!r}을(를) 불러오지 못했습니다: {exc}"
                return
        # 프레임 한도의 기준은 enable 직전 샘플이다. enable 직후 첫 샘플을 기준으로 하면 그 사이에 진행한 프레임이 빠진다.
        result.pre_enable_frame = state_frame(result.last_state)
        # 호스트 API의 enable()은 반환 코드('ok'·'not_playing'·'no_policy' 등)를 준다. 옵션은 무시될 수 있다.
        code = conn.evaluate(f"window.taiseiAI.enable({json.dumps(options)})", await_promise=True, timeout=30)
        result.started_at = utc_now()
        if isinstance(code, str) and code not in ("ok", "noop"):
            result.status, result.reason = "error", "policy_error" if code in ("no_policy", "policy_error") else "runner_error"
            result.detail = f"enable()이 {code!r}를 돌려줬습니다"
            return
        result.t_enable = time.monotonic()
        result.enable_frame = state_frame(self._poll(conn, index, result).get("ai"))
        deadline = t1 + cfg.wall_timeout_s
        while True:
            if conn.closed.is_set():
                result.status, result.reason = "error", "runner_error"
                result.detail = f"실행 중 브라우저 연결이 끊겼습니다: {conn.close_reason}"
                break
            data = self._poll(conn, index, result)
            shell_state = (data.get("shell") or {}).get("state")
            end_event = next((e for e in reversed(result.events) if isinstance(e, dict) and e.get("type") == "episode_end"), None)
            if end_event is not None:
                status = end_event.get("status")
                result.status = status if status in ("completed", "error", "aborted") else "completed"
                result.reason = str(end_event.get("reason") or "runner_error")
                result.evaluable = result.status == "completed"
                break
            derived = self._derive_end(data.get("ai"), result)
            if derived is not None:
                result.status, result.reason, result.detail = derived
                result.evaluable = result.status == "completed"
                break
            if shell_state in ENDED_STATES:
                result.status, result.reason = "error", "runner_error"
                result.detail = f"실행 중 셸이 {shell_state} 상태가 됐습니다: {(data.get('shell') or {}).get('error', '')}"
                break
            if time.monotonic() >= deadline:
                result.status, result.reason = "timeout", "wall_timeout"
                result.detail = f"벽시계 한도 {cfg.wall_timeout_s}초 초과"
                break
            time.sleep(self._poll_delay(data.get("ai"), result))
        result.running_s = round(time.monotonic() - t1, 3)

    def _derive_end(self, state: dict | None, result: EpisodeResult):
        """state()의 소유권 전환·프레임으로 에피소드 끝을 파생한다. 끝이 아니면 None."""
        if not isinstance(state, dict):
            return None
        owner = owner_of(state)
        reason = reason_of(state)
        if owner is not None:
            self._record_owner(result, owner, reason or "none", state_frame(state))
        outcome = DERIVED_END.get((owner, reason))
        if outcome is not None:
            return (*outcome, f"브리지 상태에서 파생: {owner}/{reason}")
        frame = state_frame(state)
        base = self._baseline(result)
        if frame is not None and base is not None and frame - base >= self.cfg.max_frames:
            return ("completed", "frame_limit",
                    f"runner_detected: 프레임 {base}→{frame} (경과 {frame - base}, 한도 {self.cfg.max_frames}, "
                    f"초과 {frame - base - self.cfg.max_frames}; 폴링 간격만큼 넘을 수 있어 정확 N프레임 비교에 쓰지 않는다)")
        return None

    @staticmethod
    def _baseline(result: EpisodeResult):
        return result.pre_enable_frame if result.pre_enable_frame is not None else result.enable_frame

    def _poll_delay(self, state: dict | None, result: EpisodeResult) -> float:
        """프레임 한도가 가까우면 폴링 간격을 줄여 한도를 넘는 프레임 수를 줄인다(60fps에서 0.25초 = 15프레임)."""
        frame = state_frame(state)
        base = self._baseline(result)
        if frame is not None and base is not None:
            if self.cfg.max_frames - (frame - base) <= 120:
                return 0.04
        return POLL_INTERVAL_S

    def _has_method(self, conn: CdpConnection, name: str) -> bool:
        return bool(conn.evaluate(f"typeof (window.taiseiAI && window.taiseiAI.{name}) === 'function'"))

    def _bridge_ready(self, conn: CdpConnection, index: int, result: EpisodeResult) -> bool:
        data = self._poll(conn, index, result)
        ai = data.get("ai")
        return bool(data.get("bridge") and data.get("hooked") and (ai is None or ai.get("ready", True)))

    # ---- 정리 ----
    def _finish(self, conn: CdpConnection | None, browser: Browser, index: int, result: EpisodeResult) -> None:
        """입력 해제 확인 → 증거 수집 → 페이지·브라우저 종료. 예외가 나도 끝까지 진행한다."""
        try:
            if conn is not None and not conn.closed.is_set():
                self._guard("입력 해제 확인", index, result, lambda: self._release_inputs(conn, index, result))
                self._guard("증거 수집", index, result, lambda: self._collect_evidence(conn, index, result))
        finally:
            # 앞 단계가 예외·중단으로 끝나도 브라우저는 반드시 닫는다.
            try:
                result.cleanup = browser.close()
            except Exception as exc:  # noqa: BLE001 - 종료 실패도 증거로 남긴다
                result.cleanup = {"forced": [], "remaining": None, "profile_removed": None, "errors": [repr(exc)]}
                result.cleanup_errors.append(f"브라우저 종료 예외: {exc!r}")
            self.logger.log(f"episode {index}: 브라우저 정리 {result.cleanup}")
            result.ended_at = utc_now()

    def _guard(self, label: str, index: int, result: EpisodeResult, action) -> None:
        """정리 단계 하나를 실행하고, 예외는 기록만 한 채 다음 단계가 실행되게 한다(Ctrl+C 등 BaseException은 그대로 올린다)."""
        try:
            action()
        except Exception as exc:  # noqa: BLE001
            result.cleanup_errors.append(f"{label} 예외: {exc!r}")
            self.logger.log(f"episode {index}: {label} 중 예외: {exc!r}", "ERROR")

    def _release_inputs(self, conn: CdpConnection, index: int, result: EpisodeResult) -> None:
        if not result.bridge_present:
            result.input_release = {"released": None, "detail": "no_bridge"}
            return
        try:
            conn.evaluate("window.taiseiAI.disable('host_request')", await_promise=True, timeout=15)
            time.sleep(0.2)  # 한 프레임 이상 지나 입력이 실제로 풀리게 한다.
            data = self._poll(conn, index, result)
            state = data.get("ai") or {}
            owner = owner_of(state)
            inp = state.get("input")
            if isinstance(inp, dict):
                counters = {k: inp.get(k, 0) for k in ("hold", "pending_edges", "queued_actions")}
                released = owner in ("manual", "ai_suspended") and not any(counters.values())
                result.input_release = {"released": released, "basis": "counters", "owner_state": owner,
                                        "input": counters, "detail": "ok" if released else "입력이 해제되지 않았습니다"}
            elif owner is not None:
                # 입력 카운터가 없으면 소유권만 증거다. 브리지는 disable에서 대기 액션·엣지를 모두 버린다(CONTRACT 4.1).
                result.input_release = {"released": owner == "manual", "basis": "owner_state", "owner_state": owner,
                                        "detail": "ok" if owner == "manual" else "disable 뒤에도 manual이 아닙니다"}
            else:
                result.input_release = {"released": None, "detail": "state()가 소유권·입력 정보를 주지 않았습니다", "state": state}
        except Exception as exc:  # noqa: BLE001 - 연결·파일·형식 오류 모두 '확인 실패(unknown)'이지 해제 성공이 아니다
            result.input_release = {"released": None, "detail": f"확인 실패: {exc!r}"}

    def _collect_evidence(self, conn: CdpConnection, index: int, result: EpisodeResult) -> None:
        try:
            self._pump_console(conn, index, result)
            lines = conn.evaluate("(window.taiseiShell && window.taiseiShell.logLines) ? window.taiseiShell.logLines.slice() : []")
            self._game_file.write(f"== episode {index:04d} ==\n" + "\n".join(map(str, lines or [])) + "\n")
            self._game_file.flush()
            result.evidence["game_log"] = "logs/game.log"
            result.evidence["console_log"] = "logs/browser-console.log"
            if result.status != "completed" or result.startup_failed or self.cfg.mode == "smoke":
                shot = conn.call("Page.captureScreenshot", {"format": "png"}, timeout=15).get("data")
                if shot:
                    path = self.run_dir.episode_extra_dir(index) / "last-screen.png"
                    path.write_bytes(base64.b64decode(shot))
                    result.evidence["screenshot"] = f"episodes/{index:04d}/last-screen.png"
        except Exception as exc:  # noqa: BLE001
            result.evidence_errors.append(f"증거 수집 실패: {exc!r}")
            self.logger.log(f"episode {index}: 증거 수집 일부 실패: {exc!r}", "WARN")
