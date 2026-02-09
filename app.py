#!/usr/bin/env python3
import argparse
import json
import os
import random
import re
import signal
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

APP_ROOT = Path(__file__).resolve().parent


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def expand_path(value):
    return str(Path(value).expanduser())


def load_config():
    cfg = {
        "data_root": "~/data",
        "python_bin": "python3",
        "collect_script": "",
        "collect_workdir": "",
        "collect_extra_args": [],
        "collect_shell_template": "",
        "replay_shell_template": "",
        "auto_start_stack": True,
        "stack_workdir": "",
        "roscore_cmd": "",
        "arm_launch_cmd": "",
        "camera_launch_cmd": "",
        "camera_pre_cmd": "",
        "topic_check_cmd": "source /opt/ros/noetic/setup.bash && rostopic list",
        "topic_echo_cmd": "source /opt/ros/noetic/setup.bash && timeout {timeout}s rostopic echo -n 1 {topic}",
        "topic_echo_timeout": 2,
        "require_topic_messages": True,
        "roscore_check_cmd": "",
        "required_topics": [],
        "optional_topics": [],
        "topic_check_retries": 1,
        "topic_check_delay": 0,
        "stack_start_delay": 0,
        "tail_lines": 200,
    }
    config_path = APP_ROOT / "config.json"
    example_path = APP_ROOT / "config.example.json"
    sync_mode = os.environ.get("SYNC_CONFIG_FROM_EXAMPLE", "1").lower()
    force_sync = sync_mode not in ("0", "false", "no")
    if example_path.exists() and (force_sync or not config_path.exists()):
        try:
            shutil.copyfile(example_path, config_path)
        except Exception:
            pass
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            file_cfg = json.load(f)
        if isinstance(file_cfg, dict):
            cfg.update(file_cfg)
    env_map = {
        "DATA_ROOT": "data_root",
        "PYTHON_BIN": "python_bin",
        "COLLECT_SCRIPT": "collect_script",
        "COLLECT_WORKDIR": "collect_workdir",
        "COLLECT_SHELL_TEMPLATE": "collect_shell_template",
        "REPLAY_SHELL_TEMPLATE": "replay_shell_template",
    }
    for env_key, cfg_key in env_map.items():
        if env_key in os.environ:
            cfg[cfg_key] = os.environ[env_key]
    for path_key in (
        "data_root",
        "collect_script",
        "collect_workdir",
        "stack_workdir",
    ):
        value = cfg.get(path_key)
        if value:
            cfg[path_key] = expand_path(value)
    return cfg


CONFIG = load_config()

DATA_ROOT = expand_path(CONFIG["data_root"])
TAIL_LINES = int(CONFIG.get("tail_lines", 200))

STATE_LOCK = threading.Lock()
STATE = {
    "session": None,
    "next_episode": 0,
    "current_episode": None,
    "running": False,
    "last_exit": None,
    "last_error": None,
    "last_log": deque(maxlen=TAIL_LINES),
    "episodes": [],
    "selected_episode": None,
    "last_replay": None,
    "stack_running": False,
    "stack_processes": {},
    "stack_log": deque(maxlen=TAIL_LINES),
    "topic_status": {
        "required": [],
        "optional": [],
        "present": [],
        "missing": [],
        "missing_optional": [],
        "missing_data": [],
        "missing_optional_data": [],
        "last_check": None,
        "error": None,
    },
}


def add_log_line(line):
    with STATE_LOCK:
        STATE["last_log"].append(line)


def add_stack_log_line(line):
    with STATE_LOCK:
        STATE["stack_log"].append(line)


def sanitize_token(value):
    if not value:
        return ""
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        return ""
    return value


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def session_paths(user_id, task_name):
    dataset_dir = Path(DATA_ROOT) / user_id / task_name
    meta_dir = dataset_dir / ".meta"
    logs_dir = meta_dir / "logs"
    return dataset_dir, meta_dir, logs_dir


def scan_episode_indices(dataset_dir):
    indices = set()
    try:
        for name in os.listdir(dataset_dir):
            match = re.match(r"episode_(\d+)", name)
            if match:
                indices.add(int(match.group(1)))
    except FileNotFoundError:
        return []
    return sorted(indices)


def write_meta(meta_dir, data):
    meta_path = meta_dir / "session.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def append_event(meta_dir, data):
    events_path = meta_dir / "episodes.jsonl"
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data) + "\n")


def build_collect_command(dataset_dir, task_name, episode_idx):
    if CONFIG.get("collect_shell_template"):
        template = CONFIG["collect_shell_template"]
        cmd = template.format(
            dataset_dir=dataset_dir,
            task_name=task_name,
            episode_idx=episode_idx,
            python=CONFIG.get("python_bin", "python3"),
            collect_script=CONFIG.get("collect_script", ""),
        )
        return ["bash", "-lc", cmd]
    if not CONFIG.get("collect_script"):
        return None
    cmd = [
        CONFIG.get("python_bin", "python3"),
        CONFIG["collect_script"],
        "--dataset_dir",
        str(dataset_dir),
        "--task_name",
        task_name,
        "--episode_idx",
        str(episode_idx),
    ]
    extra = CONFIG.get("collect_extra_args") or []
    cmd.extend(extra)
    return cmd


class EpisodeRunner:
    def __init__(self):
        self.process = None
        self.thread = None

    def start(self, cmd, workdir, log_path, meta_dir, dataset_dir, episode_idx):
        env = os.environ.copy()
        ensure_dir(log_path.parent)
        log_file = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=workdir or None,
            text=True,
            bufsize=1,
            env=env,
        )
        self.process = proc

        def _reader():
            with log_file:
                for line in proc.stdout:
                    line = line.rstrip()
                    with STATE_LOCK:
                        STATE["last_log"].append(line)
                    log_file.write(line + "\n")
            proc.wait()
            episodes = scan_episode_indices(dataset_dir)
            with STATE_LOCK:
                STATE["running"] = False
                STATE["last_exit"] = proc.returncode
                STATE["current_episode"] = None
                STATE["last_error"] = None if proc.returncode == 0 else "collect_failed"
                STATE["episodes"] = episodes
                if episodes:
                    STATE["next_episode"] = max(episodes) + 1
            append_event(
                meta_dir,
                {
                    "episode": episode_idx,
                    "event": "end",
                    "exit_code": proc.returncode,
                    "timestamp": now_iso(),
                },
            )
            self.process = None

        thread = threading.Thread(target=_reader, daemon=True)
        self.thread = thread
        thread.start()

    def stop(self):
        if not self.process:
            return False
        try:
            self.process.send_signal(signal.SIGINT)
            return True
        except Exception:
            return False


RUNNER = EpisodeRunner()


class StackRunner:
    def __init__(self):
        self.processes = {}

    def start(self, name, cmd, workdir, log_path):
        if name in self.processes and self.processes[name].poll() is None:
            return False
        ensure_dir(log_path.parent)
        log_file = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            ["bash", "-lc", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=workdir or None,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
        self.processes[name] = proc

        def _reader():
            with log_file:
                for line in proc.stdout:
                    line = line.rstrip()
                    add_stack_log_line(f"[{name}] {line}")
                    log_file.write(line + "\n")
            proc.wait()
            with STATE_LOCK:
                proc_state = STATE["stack_processes"].get(name, {})
                proc_state["running"] = False
                proc_state["exit_code"] = proc.returncode
                STATE["stack_processes"][name] = proc_state
                STATE["stack_running"] = any(
                    p.poll() is None for p in self.processes.values()
                )
            add_stack_log_line(f"[{name}] exited with code {proc.returncode}")

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        return True

    def stop_all(self):
        stopped = False
        for proc in list(self.processes.values()):
            if proc and proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGINT)
                    stopped = True
                except Exception:
                    continue
        return stopped


STACK = StackRunner()


def stack_commands():
    return {
        "roscore": CONFIG.get("roscore_cmd", ""),
        "arm": CONFIG.get("arm_launch_cmd", ""),
        "camera": CONFIG.get("camera_launch_cmd", ""),
    }


def stack_logs_dir(session):
    if session:
        return Path(session["dataset_dir"]) / ".meta" / "logs"
    return APP_ROOT / ".stack_logs"


def ensure_stack_running():
    with STATE_LOCK:
        if STATE["stack_running"]:
            return True, None
    cmds = stack_commands()
    if not any(cmds.values()):
        add_stack_log_line("[error] stack_not_configured")
        return False, "stack_not_configured"
    workdir = CONFIG.get("stack_workdir") or None
    if workdir and not Path(workdir).exists():
        add_stack_log_line(f"[error] stack_workdir_missing: {workdir}")
        return False, "stack_workdir_missing"
    with STATE_LOCK:
        STATE["stack_processes"] = {}
        STATE["stack_log"].clear()
        STATE["stack_running"] = True
    session = STATE["session"]
    logs_dir = stack_logs_dir(session)
    ensure_dir(logs_dir)
    delay = float(CONFIG.get("stack_start_delay", 0) or 0)

    def _start_named(name, external=False):
        cmd = cmds.get(name)
        if not cmd and not external:
            return
        with STATE_LOCK:
            STATE["stack_processes"][name] = {
                "cmd": cmd,
                "running": True,
                "exit_code": None,
                "external": external,
            }
        if not external:
            log_path = logs_dir / f"stack_{name}.log"
            started = STACK.start(name, cmd, workdir, log_path)
            if not started:
                add_stack_log_line(f"[warn] {name} already running")

    roscore_running = roscore_is_running()
    if roscore_running:
        add_stack_log_line("[info] roscore already running; skip start")
        _start_named("roscore", external=True)
    else:
        _start_named("roscore")
    if delay > 0:
        time.sleep(delay)
    _start_named("arm")
    if delay > 0:
        time.sleep(delay)
    pre_cmd = CONFIG.get("camera_pre_cmd")
    if pre_cmd:
        try:
            subprocess.run(["bash", "-lc", pre_cmd], check=False)
            add_stack_log_line("[info] camera_pre_cmd executed")
        except Exception as exc:
            add_stack_log_line(f"[warn] camera_pre_cmd failed: {exc}")
    _start_named("camera")
    with STATE_LOCK:
        STATE["stack_running"] = any(
            p.poll() is None for p in STACK.processes.values()
        )
    return True, None


def topic_has_data(topic, timeout):
    cmd_tpl = CONFIG.get("topic_echo_cmd")
    if not cmd_tpl:
        return False, "topic_echo_not_configured"
    cmd = cmd_tpl.format(topic=topic, timeout=timeout)
    try:
        result = subprocess.run(
            ["bash", "-lc", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout + 1,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True, None
        if result.returncode == 124:
            return False, "timeout"
        return False, result.stderr.strip() or "no_data"
    except Exception as exc:
        return False, str(exc)


def run_topic_check(with_data=None):
    cmd = CONFIG.get("topic_check_cmd")
    required = CONFIG.get("required_topics") or []
    optional = CONFIG.get("optional_topics") or []
    retries = int(CONFIG.get("topic_check_retries", 1) or 1)
    delay = float(CONFIG.get("topic_check_delay", 0) or 0)
    if with_data is None:
        with_data = bool(CONFIG.get("require_topic_messages", False))
    if not cmd:
        return {
            "required": required,
            "optional": optional,
            "present": [],
            "missing": required,
            "missing_optional": optional,
            "missing_data": required if with_data else [],
            "missing_optional_data": optional if with_data else [],
            "last_check": now_iso(),
            "error": "topic_check_not_configured",
        }
    last_status = None
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["bash", "-lc", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            output = result.stdout.splitlines()
            present = sorted(set(t for t in output if t.startswith("/")))
            missing = [t for t in required if t not in present]
            missing_optional = [t for t in optional if t not in present]
            missing_data = []
            missing_optional_data = []
            if with_data and not missing:
                timeout = int(CONFIG.get("topic_echo_timeout", 2) or 2)
                for topic in required:
                    if topic not in present:
                        continue
                    ok, _ = topic_has_data(topic, timeout)
                    if not ok:
                        missing_data.append(topic)
                for topic in optional:
                    if topic not in present:
                        continue
                    ok, _ = topic_has_data(topic, timeout)
                    if not ok:
                        missing_optional_data.append(topic)
            last_status = {
                "required": required,
                "optional": optional,
                "present": present,
                "missing": missing,
                "missing_optional": missing_optional,
                "missing_data": missing_data,
                "missing_optional_data": missing_optional_data,
                "last_check": now_iso(),
                "error": None if result.returncode == 0 else result.stderr.strip(),
            }
            if not missing and (not with_data or not missing_data):
                return last_status
        except Exception as exc:
            last_status = {
                "required": required,
                "optional": optional,
                "present": [],
                "missing": required,
                "missing_optional": optional,
                "missing_data": required if with_data else [],
                "missing_optional_data": optional if with_data else [],
                "last_check": now_iso(),
                "error": str(exc),
            }
        if attempt < retries - 1 and delay > 0:
            time.sleep(delay)
    return last_status


def roscore_is_running():
    cmd = CONFIG.get("roscore_check_cmd") or CONFIG.get("topic_check_cmd")
    if not cmd:
        return False
    try:
        result = subprocess.run(
            ["bash", "-lc", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False

app = Flask(__name__, static_folder="static", static_url_path="/static")


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


@app.route("/api/status", methods=["GET"])
def api_status():
    with STATE_LOCK:
        session = STATE["session"]
        data = {
            "session": session,
            "next_episode": STATE["next_episode"],
            "current_episode": STATE["current_episode"],
            "running": STATE["running"],
            "last_exit": STATE["last_exit"],
            "last_error": STATE["last_error"],
            "episodes": STATE["episodes"],
            "selected_episode": STATE["selected_episode"],
            "last_replay": STATE["last_replay"],
            "last_log": list(STATE["last_log"]),
            "stack_running": STATE["stack_running"],
            "stack_processes": STATE["stack_processes"],
            "stack_log": list(STATE["stack_log"]),
            "topic_status": STATE["topic_status"],
        }
    data["data_root"] = DATA_ROOT
    data["collect_configured"] = bool(
        CONFIG.get("collect_shell_template") or CONFIG.get("collect_script")
    )
    return jsonify(data)


@app.route("/api/session/start", methods=["POST"])
def api_session_start():
    payload = request.get_json(silent=True) or {}
    user_id = sanitize_token(payload.get("user"))
    task_name = sanitize_token(payload.get("task"))
    if not user_id or not task_name:
        return jsonify({"ok": False, "error": "invalid_user_or_task"}), 400
    dataset_dir, meta_dir, logs_dir = session_paths(user_id, task_name)
    ensure_dir(dataset_dir)
    ensure_dir(meta_dir)
    ensure_dir(logs_dir)
    episodes = scan_episode_indices(dataset_dir)
    next_episode = (episodes[-1] + 1) if episodes else 0
    session = {
        "user": user_id,
        "task": task_name,
        "dataset_dir": str(dataset_dir),
        "created_at": now_iso(),
    }
    write_meta(meta_dir, session)
    with STATE_LOCK:
        STATE["session"] = session
        STATE["episodes"] = episodes
        STATE["next_episode"] = next_episode
        STATE["current_episode"] = None
        STATE["running"] = False
        STATE["last_exit"] = None
        STATE["last_error"] = None
        STATE["last_log"].clear()
        STATE["selected_episode"] = None
        STATE["last_replay"] = None
    return jsonify({"ok": True, "session": session, "next_episode": next_episode})


@app.route("/api/episode/start", methods=["POST"])
def api_episode_start():
    with STATE_LOCK:
        session = STATE["session"]
        running = STATE["running"]
        next_episode = STATE["next_episode"]
    if not session:
        add_log_line("[error] no_session")
        return jsonify({"ok": False, "error": "no_session"}), 400
    if running:
        add_log_line("[error] already_running")
        return jsonify({"ok": False, "error": "already_running"}), 409
    if CONFIG.get("auto_start_stack", False):
        ok, err = ensure_stack_running()
        if not ok:
            return jsonify({"ok": False, "error": err}), 400
        status = run_topic_check()
        with STATE_LOCK:
            STATE["topic_status"] = status
        missing_required = status.get("missing") or []
        missing_optional = status.get("missing_optional") or []
        missing_data = status.get("missing_data") or []
        missing_optional_data = status.get("missing_optional_data") or []
        if missing_required:
            add_log_line(f"[error] topics_missing: {', '.join(missing_required)}")
            if missing_optional:
                add_log_line(
                    f"[warn] topics_missing_optional: {', '.join(missing_optional)}"
                )
            return jsonify({"ok": False, "error": "topics_missing"}), 400
        if missing_data:
            add_log_line(f"[error] topics_no_data: {', '.join(missing_data)}")
            if missing_optional_data:
                add_log_line(
                    f"[warn] topics_no_data_optional: {', '.join(missing_optional_data)}"
                )
            return jsonify({"ok": False, "error": "topics_no_data"}), 400
    cmd = build_collect_command(
        session["dataset_dir"], session["task"], next_episode
    )
    if not cmd:
        add_log_line("[error] collect_not_configured")
        return jsonify({"ok": False, "error": "collect_not_configured"}), 400
    dataset_dir = Path(session["dataset_dir"])
    meta_dir = dataset_dir / ".meta"
    log_path = meta_dir / "logs" / f"episode_{next_episode}.log"
    workdir = CONFIG.get("collect_workdir") or None
    if workdir and not Path(workdir).exists():
        add_log_line(f"[error] collect_workdir_missing: {workdir}")
        return (
            jsonify({"ok": False, "error": "collect_workdir_missing", "path": workdir}),
            400,
        )
    with STATE_LOCK:
        STATE["running"] = True
        STATE["current_episode"] = next_episode
        STATE["last_exit"] = None
        STATE["last_error"] = None
        STATE["last_log"].clear()
    append_event(
        meta_dir,
        {"episode": next_episode, "event": "start", "timestamp": now_iso()},
    )
    try:
        RUNNER.start(cmd, workdir, log_path, meta_dir, dataset_dir, next_episode)
    except FileNotFoundError as exc:
        add_log_line(f"[error] collect_launch_failed: {exc}")
        with STATE_LOCK:
            STATE["running"] = False
            STATE["current_episode"] = None
            STATE["last_exit"] = None
            STATE["last_error"] = "collect_launch_failed"
        return (
            jsonify({"ok": False, "error": "collect_launch_failed", "detail": str(exc)}),
            500,
        )
    except OSError as exc:
        add_log_line(f"[error] collect_launch_failed: {exc}")
        with STATE_LOCK:
            STATE["running"] = False
            STATE["current_episode"] = None
            STATE["last_exit"] = None
            STATE["last_error"] = "collect_launch_failed"
        return (
            jsonify({"ok": False, "error": "collect_launch_failed", "detail": str(exc)}),
            500,
        )
    with STATE_LOCK:
        STATE["next_episode"] = next_episode + 1
    return jsonify({"ok": True, "episode": next_episode, "cmd": cmd})


@app.route("/api/episode/stop", methods=["POST"])
def api_episode_stop():
    stopped = RUNNER.stop()
    if not stopped:
        with STATE_LOCK:
            if STATE["running"] or STATE["current_episode"] is not None:
                STATE["running"] = False
                STATE["current_episode"] = None
                STATE["last_error"] = "no_running_process"
                add_log_line("[warn] stop called with no process; state reset")
                return jsonify({"ok": True, "note": "state_reset"})
        return jsonify({"ok": False, "error": "no_running_process"}), 409
    return jsonify({"ok": True, "note": "signal_sent"})


@app.route("/api/stack/start", methods=["POST"])
def api_stack_start():
    ok, err = ensure_stack_running()
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/stack/stop", methods=["POST"])
def api_stack_stop():
    stopped = STACK.stop_all()
    with STATE_LOCK:
        STATE["stack_running"] = False
        for name, proc_state in STATE["stack_processes"].items():
            proc_state["running"] = False
    if not stopped:
        return jsonify({"ok": False, "error": "stack_not_running"}), 409
    add_stack_log_line("[info] stop signal sent to stack")
    return jsonify({"ok": True})


@app.route("/api/topics/check", methods=["POST"])
def api_topics_check():
    status = run_topic_check()
    with STATE_LOCK:
        STATE["topic_status"] = status
    return jsonify({"ok": True, "status": status})


@app.route("/api/episodes", methods=["GET"])
def api_episodes():
    with STATE_LOCK:
        session = STATE["session"]
    if not session:
        return jsonify({"ok": False, "error": "no_session"}), 400
    dataset_dir = session["dataset_dir"]
    episodes = scan_episode_indices(dataset_dir)
    with STATE_LOCK:
        STATE["episodes"] = episodes
        if episodes:
            STATE["next_episode"] = max(episodes) + 1
    return jsonify({"ok": True, "episodes": episodes})


@app.route("/api/episode/random", methods=["POST"])
def api_episode_random():
    with STATE_LOCK:
        session = STATE["session"]
        episodes = list(STATE["episodes"])
    if not session:
        return jsonify({"ok": False, "error": "no_session"}), 400
    if not episodes:
        return jsonify({"ok": False, "error": "no_episodes"}), 400
    chosen = random.choice(episodes)
    with STATE_LOCK:
        STATE["selected_episode"] = chosen
    return jsonify({"ok": True, "episode": chosen})


@app.route("/api/replay/prepare", methods=["POST"])
def api_replay_prepare():
    with STATE_LOCK:
        session = STATE["session"]
        selected = STATE["selected_episode"]
    if not session:
        return jsonify({"ok": False, "error": "no_session"}), 400
    if selected is None:
        return jsonify({"ok": False, "error": "no_selected_episode"}), 400
    payload = {
        "dataset_dir": session["dataset_dir"],
        "task": session["task"],
        "episode": selected,
        "note": "replay_not_implemented",
        "timestamp": now_iso(),
    }
    with STATE_LOCK:
        STATE["last_replay"] = payload
    return jsonify({"ok": True, "replay": payload})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
