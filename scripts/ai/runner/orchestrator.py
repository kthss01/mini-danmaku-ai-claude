"""실행 전체 흐름: 인자 검증 → run 폴더 → 서버 → 에피소드 반복 → 요약 → 정리."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from collections import Counter
from pathlib import Path

from . import config as cfgmod
from .browser import find_browser
from .config import ArgError, RunConfig, REPO_ROOT
from .episode import EpisodeDriver, EpisodeResult, state_episode_id, state_frame
from .provenance import BuildError, code_block, inspect_site, main_commit_and_dirty
from .runfiles import (EPISODE_SCHEMA, RUN_SCHEMA, SUMMARY_SCHEMA, RunDir, RunLogger, new_run_id, utc_now,
                       write_json)
from .server import ServerError, SiteServer

DEFAULT_RUN_ROOT = REPO_ROOT / "artifacts" / "runs"


def _episode_document(cfg: RunConfig, run_id: str, code: dict, result: EpisodeResult) -> dict:
    """세션 4(#23) 에피소드 스키마의 실행기 담당 블록(run·code·config)과 실행 사실을 채운다.

    result·events·metrics는 평가 도구가 원시 이벤트(evidence.events)에서 만든다.
    run.status_by_runner는 평가 도구가 상태를 바꿀 때만 쓰므로 여기서 쓰지 않는다.
    """
    extra_dir = f"episodes/{result.index:04d}"
    return {
        "schema": EPISODE_SCHEMA,
        "run_id": run_id,
        "episode_id": state_episode_id(result.last_state),
        "experiment_id": cfg.experiment_id,
        "episode_index": result.index,
        "started_at": result.started_at,
        "ended_at": result.ended_at,
        "code": code,
        "config": {
            "scenario": cfg.scenario(),
            "policy": {"name": cfg.policy, "version": cfg.policy_version, "params": cfg.policy_params,
                       "params_sha256": hashlib.sha256(json.dumps(cfg.policy_params, sort_keys=True, ensure_ascii=False,
                                                                  separators=(",", ":")).encode("utf-8")).hexdigest()},
            # 시드를 지정하지 않으므로 게임이 makeseed()를 쓴다. 실제 값은 브리지 관측(seed_hi:seed_lo)이 알려 준다.
            "seed": {"control": "random", "required": False, "requested": None, "actual": None, "source": None},
            "limits": {"max_frames": cfg.max_frames, "wall_timeout_s": cfg.wall_timeout_s},
            "mode": cfg.mode,
            "shot_inverted": cfg.shot_inverted,
            "shot_inverted_source": "forced" if cfg.shot_inverted is not None else "unknown",
            "game_args": cfg.game_args(),
        },
        "run": {
            "status": result.status,
            "reason": result.reason,
            "evaluable": result.evaluable,
            "detail": result.detail,
            "elapsed_s": _elapsed_s(result),
            "error_message": result.detail if result.status in ("error", "timeout") else None,
        },
        "owner_transitions": result.owner_transitions,
        "final": {"gameover": (result.last_state or {}).get("gameover") if isinstance(result.last_state, dict) else None,
                  "last_frame": state_frame(result.last_state)},
        "result": None,
        "runner": {
            "startup_s": result.startup_s,
            "running_s": result.running_s,
            "bridge_present": result.bridge_present,
            "shell_states": result.shell_states,
            "shell_final": result.shell_final,
            "first_state": result.first_state,
            "last_state": result.last_state,
            "console_errors": result.console_errors,
            "dropped_events": result.dropped_events,
            "input_release": result.input_release,
            "cleanup": result.cleanup,
            "cleanup_status": cleanup_status(result),
            "cleanup_errors": result.cleanup_errors,
            "evidence_errors": result.evidence_errors,
            "frame_progress": _frame_progress(cfg, result),
            "event_count": len(result.events),
        },
        "evidence": {
            **result.evidence,
            "events": f"{extra_dir}.events.jsonl",
            "artifacts": result.artifacts,
            "log": "logs/runner.log",
        },
    }


def _elapsed_s(result: EpisodeResult):
    if result.startup_s is None and result.running_s is None:
        return None
    return round((result.startup_s or 0) + (result.running_s or 0), 3)


def _write_episode(run_dir: RunDir, doc: dict, result: EpisodeResult) -> None:
    events_path = run_dir.episodes / f"{result.index:04d}.events.jsonl"
    with open(events_path, "w", encoding="utf-8") as handle:
        for event in result.events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    write_json(run_dir.episode_path(result.index), doc)


def cleanup_status(result: EpisodeResult) -> str:
    """에피소드의 정리 판정. leak(누수 확정) > unknown(확인 못 함) > clean. unknown은 정리 검증 성공이 아니다."""
    cleanup = result.cleanup or {}
    released = (result.input_release or {}).get("released")
    if cleanup.get("remaining") or cleanup.get("profile_removed") is False or released is False:
        return "leak"
    # 정리 결과가 없거나, 프로세스·프로필 확인이 불가하거나, 정리 단계 예외가 있었다.
    if (not cleanup or cleanup.get("remaining") is None or cleanup.get("profile_removed") is None
            or cleanup.get("errors") or result.cleanup_errors):
        return "unknown"
    # 브리지가 있었는데 입력 해제를 확인하지 못했다. 브리지 없는 smoke(no_bridge)는 해제할 입력이 없다.
    if result.bridge_present and released is None:
        return "unknown"
    return "clean"


def server_cleanup_status(info: dict) -> str:
    if info.get("port_closed") is False or info.get("process_gone") is False:
        return "leak"
    if info.get("port_closed") is None or info.get("process_gone") is None or info.get("error"):
        return "unknown"
    return "clean"


def _frame_progress(cfg: RunConfig, result: EpisodeResult) -> dict:
    """프레임 한도 판단 근거. 폴링으로 감지한 한도는 정확 N프레임 비교에 쓰지 않는다."""
    base = result.pre_enable_frame if result.pre_enable_frame is not None else result.enable_frame
    elapsed = None if base is None or result.end_frame is None else result.end_frame - base
    detected = None
    if result.reason == "frame_limit":
        detected = "runner" if "runner_detected" in result.detail else "host"
    return {"max_frames": cfg.max_frames, "pre_enable_frame": result.pre_enable_frame,
            "first_sample_frame": result.enable_frame, "end_frame": result.end_frame, "elapsed_frames": elapsed,
            "exceeded_by": None if elapsed is None else max(0, elapsed - cfg.max_frames),
            "limit_detected_by": detected}


def _failure_run_json(run_dir: RunDir, argv: list[str], exit_code: int, message: str, run_id: str) -> None:
    write_json(run_dir.path / "run.json", {
        "schema": RUN_SCHEMA, "run_id": run_id, "experiment_id": None, "command": argv, "finished": True,
        "started_at": utc_now(), "ended_at": utc_now(), "exit_code": exit_code, "error": message,
        "requested_episodes": 0, "attempted_episodes": 0,
    })


def run(argv: list[str]) -> int:
    run_id = new_run_id()
    started_at = utc_now()
    try:
        cfg = cfgmod.parse_args(argv)
    except ArgError as exc:
        print(f"run.py: 인자 오류: {exc}", file=sys.stderr)
        _record_early_failure(argv, run_id, cfgmod.EXIT_BAD_ARGS, f"인자 오류: {exc}")
        return cfgmod.EXIT_BAD_ARGS

    root = Path(cfg.run_root) if cfg.run_root else DEFAULT_RUN_ROOT
    run_dir = RunDir(root, run_id)
    logger = RunLogger(run_dir.logs / "runner.log")
    logger.log(f"run {run_id} 시작: experiment={cfg.experiment_id} mode={cfg.mode} policy={cfg.policy} "
               f"episodes={cfg.episodes} flavor={cfg.build_flavor}")

    site = Path(cfg.site) if cfg.site else cfg.default_site()
    try:
        facts = inspect_site(cfg, site)
    except BuildError as exc:
        logger.log(f"산출물 오류: {exc}", "ERROR")
        _failure_run_json(run_dir, argv, cfgmod.EXIT_BAD_BUILD, f"산출물 오류: {exc}", run_id)
        print(f"run.py: 산출물 오류: {exc}", file=sys.stderr)
        logger.close()
        return cfgmod.EXIT_BAD_BUILD

    executable = find_browser(cfg.browser)
    if executable is None:
        message = f"브라우저를 찾지 못했습니다: {cfg.browser}"
        logger.log(message, "ERROR")
        _failure_run_json(run_dir, argv, cfgmod.EXIT_BAD_ARGS, message, run_id)
        print(f"run.py: {message}", file=sys.stderr)
        logger.close()
        return cfgmod.EXIT_BAD_ARGS

    main_commit, dirty = main_commit_and_dirty()
    code = code_block(facts, main_commit, dirty)
    shutil_copy_info(site / "build-info.json", run_dir.path / "build-info.json")

    manifest: dict = {
        "schema": RUN_SCHEMA, "run_id": run_id, "experiment_id": cfg.experiment_id, "finished": False,
        "command": argv, "config": _config_dict(cfg), "started_at": started_at, "ended_at": None,
        "exit_code": None, "code": code, "site": str(site),
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "browser": {"executable": executable, "headless": cfg.headless, "version": None},
        "server": None, "requested_episodes": cfg.episodes, "attempted_episodes": 0,
        "cleanup": None,
    }
    write_json(run_dir.path / "run.json", manifest)

    exit_code = cfgmod.EXIT_OK
    results: list[EpisodeResult] = []
    server = SiteServer(site, run_dir.logs / "server.log", port=cfg.port)
    driver: EpisodeDriver | None = None
    interrupted = False
    try:
        try:
            server.start()
        except ServerError as exc:
            logger.log(f"서버 시작 실패: {exc}", "ERROR")
            manifest["error"] = f"서버 시작 실패: {exc}"
            exit_code = cfgmod.EXIT_NO_START
            return exit_code
        manifest["server"] = {"port": server.port, "pid": server.process.pid if server.process else None}
        logger.log(f"서버 {server.url} (pid {manifest['server']['pid']})")
        driver = EpisodeDriver(cfg, run_dir, logger, server.url, facts["entry"], executable, run_id)

        for index in range(1, cfg.episodes + 1):
            try:
                result = driver.run(index)
            except KeyboardInterrupt:
                interrupted = True
                exit_code = cfgmod.EXIT_ABORTED
                logger.log("사용자 중단 요청(Ctrl+C)", "WARN")
                result = None
            except Exception as exc:  # 실행기 내부 오류: 남은 에피소드를 시도하지 못한다.
                logger.log(f"episode {index}: 실행기 내부 오류: {exc!r}", "ERROR")
                manifest["error"] = f"episode {index}: 실행기 내부 오류: {exc!r}"
                exit_code = cfgmod.EXIT_RUNNER_ERROR if index > 1 else cfgmod.EXIT_NO_START
                break
            if result is None:
                break
            results.append(result)
            _write_episode(run_dir, _episode_document(cfg, run_id, code, result), result)
            logger.log(f"episode {index}: {result.status}/{result.reason} {result.detail}")
            manifest["attempted_episodes"] = len(results)
            write_json(run_dir.path / "run.json", manifest)
            if result.interrupted:
                interrupted = True
                exit_code = cfgmod.EXIT_ABORTED
                logger.log("사용자 중단: 남은 에피소드를 시도하지 않습니다", "WARN")
                break
            if result.startup_failed:
                exit_code = cfgmod.EXIT_NO_START if index == 1 else cfgmod.EXIT_RUNNER_ERROR
                manifest["error"] = f"episode {index}: 시작하지 못했습니다: {result.detail}"
                break
    finally:
        if driver is not None:
            driver.close()
        try:
            server_info = server.stop()
        except Exception as exc:  # noqa: BLE001 - 서버 종료 실패도 기록하고 요약·종료 코드는 끝까지 만든다
            server_info = {"pid": None, "port": server.port, "port_closed": None, "process_gone": None,
                           "error": repr(exc)}
        manifest["server_stop"] = server_info
        statuses = {r.index: cleanup_status(r) for r in results}
        server_status = server_cleanup_status(server_info)
        all_statuses = [*statuses.values(), server_status]
        run_status = "leak" if "leak" in all_statuses else "unknown" if "unknown" in all_statuses else "clean"
        manifest["cleanup"] = {
            "status": run_status, "ok": run_status == "clean", "server": server_info, "server_status": server_status,
            "episodes_with_leaks": [i for i, s in statuses.items() if s == "leak"],
            "episodes_unknown": [i for i, s in statuses.items() if s == "unknown"],
        }
        # 누수 확정(leak)과 정리 확인 불가(unknown) 모두 종료 코드 6이다. 구분은 cleanup.status로 한다.
        if exit_code == cfgmod.EXIT_OK and run_status != "clean":
            exit_code = cfgmod.EXIT_CLEANUP_FAILED
        if results:
            manifest["browser"]["version"] = results[0].browser_version or None
        _write_summary(run_dir, cfg, run_id, results, exit_code, manifest["cleanup"]["ok"], code)
        manifest.update({"finished": True, "ended_at": utc_now(), "exit_code": exit_code,
                         "interrupted": interrupted})
        write_json(run_dir.path / "run.json", manifest)
        logger.log(f"run {run_id} 종료: exit_code={exit_code} cleanup={manifest['cleanup']['status']}")
        logger.close()
    print(json.dumps({"run_id": run_id, "run_dir": str(run_dir.path), "exit_code": exit_code,
                      "status_counts": dict(Counter(r.status for r in results))}, ensure_ascii=False))
    return exit_code


def _write_summary(run_dir: RunDir, cfg: RunConfig, run_id: str, results: list[EpisodeResult], exit_code: int,
                   cleanup_ok: bool, code: dict) -> None:
    """상태별 개수만 센다. 성공률 같은 지표는 평가 도구(evaluation.json)가 계산한다."""
    write_json(run_dir.path / "summary.json", {
        "schema": SUMMARY_SCHEMA, "run_id": run_id, "experiment_id": cfg.experiment_id,
        "requested": cfg.episodes, "attempted": len(results),
        "by_status": dict(Counter(r.status for r in results)),
        "by_reason": dict(Counter(f"{r.status}/{r.reason}" for r in results)),
        "exit_code": exit_code, "cleanup_ok": cleanup_ok, "build_flavor": code["build_flavor"],
        "rules_preserved": code["rules_preserved"], "mode": cfg.mode,
    })


def _config_dict(cfg: RunConfig) -> dict:
    return {key: getattr(cfg, key) for key in RunConfig.__dataclass_fields__}


def shutil_copy_info(src: Path, dst: Path) -> None:
    dst.write_bytes(src.read_bytes())


def _record_early_failure(argv: list[str], run_id: str, exit_code: int, message: str) -> None:
    """인자 오류도 기본 위치에 흔적을 남긴다(실행 폴더를 만들 수 없으면 건너뛴다)."""
    root = DEFAULT_RUN_ROOT
    if "--run-root" in argv and argv.index("--run-root") + 1 < len(argv):
        root = Path(argv[argv.index("--run-root") + 1])
    try:
        run_dir = RunDir(root, run_id)
        _failure_run_json(run_dir, argv, exit_code, message, run_id)
    except OSError:
        pass
