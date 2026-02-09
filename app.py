#!/usr/bin/env python3
import argparse
import json
import os
import random
import re
import signal
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
        "tail_lines": 200,
    }
    config_path = APP_ROOT / "config.json"
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
}


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
        return jsonify({"ok": False, "error": "no_session"}), 400
    if running:
        return jsonify({"ok": False, "error": "already_running"}), 409
    cmd = build_collect_command(
        session["dataset_dir"], session["task"], next_episode
    )
    if not cmd:
        return jsonify({"ok": False, "error": "collect_not_configured"}), 400
    dataset_dir = Path(session["dataset_dir"])
    meta_dir = dataset_dir / ".meta"
    log_path = meta_dir / "logs" / f"episode_{next_episode}.log"
    workdir = CONFIG.get("collect_workdir") or None
    if workdir and not Path(workdir).exists():
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
                return jsonify({"ok": True, "note": "state_reset"})
        return jsonify({"ok": False, "error": "no_running_process"}), 409
    return jsonify({"ok": True, "note": "signal_sent"})


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
