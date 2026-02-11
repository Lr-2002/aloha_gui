#!/usr/bin/env python3
import argparse
import atexit
import csv
import json
import os
import random
import re
import signal
import shutil
import shlex
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

APP_ROOT = Path(__file__).resolve().parent
REGISTRY_DIR = APP_ROOT / "registry"

BASE_CONFIG = None


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def expand_path(value):
    return str(Path(value).expanduser())


REGISTRY_LOCK = threading.Lock()
REGISTRY_DEFAULTS = {
    "users": [],
    "tasks": [],
    "interfaces": [],
    "episodes": [],
}


def ensure_registry_dir():
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)


def registry_path(name):
    return REGISTRY_DIR / f"{name}.json"


def load_registry(name):
    ensure_registry_dir()
    path = registry_path(name)
    if not path.exists():
        write_registry(name, REGISTRY_DEFAULTS.get(name, []))
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_registry(name, data):
    ensure_registry_dir()
    path = registry_path(name)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


def generate_id(prefix, existing):
    base = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")
    if not base:
        base = "id"
    for _ in range(100):
        suffix = f"{int(time.time())%100000}-{random.randint(100,999)}"
        candidate = f"{base}-{suffix}"
        if candidate not in existing:
            return candidate
    return f"{base}-{int(time.time())}"


def stable_id_from_name(name, existing):
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "id"
    if base not in existing:
        return base
    idx = 2
    while f"{base}-{idx}" in existing:
        idx += 1
    return f"{base}-{idx}"


def registry_get_item(items, item_id):
    for item in items:
        if item.get("id") == item_id:
            return item
    return None


def default_tasks():
    return [
        {
            "id": "pick-and-place",
            "name": "Pick and Place",
            "description": "Pick a single object and place it in a target zone.",
            "success_criteria": "Object ends inside target zone without drop.",
        },
        {
            "id": "stack-blocks",
            "name": "Stack Blocks",
            "description": "Stack multiple blocks into a stable tower.",
            "success_criteria": "All blocks stacked without collapse.",
        },
        {
            "id": "insert-peg",
            "name": "Insert Peg",
            "description": "Insert a peg into a matching hole.",
            "success_criteria": "Peg fully inserted and stable.",
        },
        {
            "id": "plug-connector",
            "name": "Plug Connector",
            "description": "Align and plug a connector into a socket.",
            "success_criteria": "Connector fully seated and aligned.",
        },
        {
            "id": "open-drawer",
            "name": "Open Drawer",
            "description": "Pull a drawer open to a marked distance.",
            "success_criteria": "Drawer opened to target distance.",
        },
        {
            "id": "close-drawer",
            "name": "Close Drawer",
            "description": "Push a drawer closed until fully seated.",
            "success_criteria": "Drawer fully closed.",
        },
        {
            "id": "press-button",
            "name": "Press Button",
            "description": "Press a target button with correct force.",
            "success_criteria": "Button actuated and released.",
        },
        {
            "id": "flip-switch",
            "name": "Flip Switch",
            "description": "Toggle a switch from one state to another.",
            "success_criteria": "Switch reaches target state.",
        },
        {
            "id": "wipe-surface",
            "name": "Wipe Surface",
            "description": "Wipe a marked area using a tool or cloth.",
            "success_criteria": "Coverage of target area achieved.",
        },
        {
            "id": "pour-liquid",
            "name": "Pour Liquid",
            "description": "Pour from a source into a target container.",
            "success_criteria": "Target reaches specified fill level without spill.",
        },
        {
            "id": "pick-from-bin",
            "name": "Pick From Bin",
            "description": "Pick an object from a bin and place on table.",
            "success_criteria": "Object removed from bin and placed correctly.",
        },
        {
            "id": "align-place",
            "name": "Align and Place",
            "description": "Align an object with a fixture before placing.",
            "success_criteria": "Object aligned within tolerance and placed.",
        },
    ]


def default_interfaces():
    return [
        {
            "id": "aloha",
            "name": "Aloha",
            "type": "aloha",
            "description": "Aloha data collection interface.",
        }
    ]


def load_tasks_from_csv(path):
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    tasks = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                name = (row.get("name") or row.get("task_name") or "").strip()
                if not name:
                    continue
                task_id = (row.get("id") or "").strip()
                record = {
                    "id": task_id,
                    "name": name,
                    "description": (row.get("description") or row.get("task_description") or "").strip(),
                    "success_criteria": (
                        row.get("success_criteria")
                        or row.get("success")
                        or row.get("criteria")
                        or ""
                    ).strip(),
                }
                tasks.append(record)
    except Exception:
        return []
    return tasks


def merge_tasks(existing, incoming):
    existing_ids = {t.get("id") for t in existing if t.get("id")}
    merged = list(existing)
    for item in incoming:
        name = item.get("name") or ""
        task_id = item.get("id") or stable_id_from_name(name, existing_ids)
        existing_ids.add(task_id)
        record = {
            "id": task_id,
            "name": name,
            "description": item.get("description", ""),
            "success_criteria": item.get("success_criteria", ""),
        }
        current = registry_get_item(merged, task_id)
        if current:
            current.update(record)
        else:
            merged.append(record)
    return merged


def normalize_tasks(items):
    existing_ids = {t.get("id") for t in items if t.get("id")}
    updated = False
    for item in items:
        if not item.get("id"):
            name = item.get("name") or ""
            item["id"] = stable_id_from_name(name, existing_ids)
            existing_ids.add(item["id"])
            updated = True
    return updated, items


def load_users_from_csv(path):
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    users = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                name = (row.get("name") or row.get("user") or row.get("user_name") or "").strip()
                if not name:
                    continue
                user_id = (row.get("id") or row.get("uid") or "").strip()
                users.append({"id": user_id, "name": name})
    except Exception:
        return []
    return users


def merge_users(existing, incoming):
    existing_ids = {u.get("id") for u in existing if u.get("id")}
    merged = list(existing)
    for item in incoming:
        name = item.get("name") or ""
        user_id = item.get("id") or stable_id_from_name(name, existing_ids)
        existing_ids.add(user_id)
        record = {"id": user_id, "name": name}
        current = registry_get_item(merged, user_id)
        if current:
            current.update(record)
        else:
            merged.append(record)
    return merged


def normalize_users(items):
    existing_ids = {u.get("id") for u in items if u.get("id")}
    updated = False
    for item in items:
        if not item.get("id"):
            name = item.get("name") or ""
            item["id"] = stable_id_from_name(name, existing_ids)
            existing_ids.add(item["id"])
            updated = True
    return updated, items


def load_interfaces_from_csv(path):
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    interfaces = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                iface_id = (row.get("id") or row.get("interface_id") or "").strip()
                name = (row.get("name") or row.get("interface") or "").strip()
                if not iface_id:
                    iface_id = stable_id_from_name(name, set())
                if not iface_id:
                    continue
                interfaces.append(
                    {
                        "id": iface_id,
                        "name": name or iface_id,
                        "type": (row.get("type") or "").strip() or iface_id,
                        "description": (row.get("description") or "").strip(),
                        "config_path": (row.get("config_path") or row.get("config") or "").strip(),
                    }
                )
    except Exception:
        return []
    return interfaces


def merge_interfaces(existing, incoming):
    existing_ids = {i.get("id") for i in existing if i.get("id")}
    merged = list(existing)
    for item in incoming:
        iface_id = item.get("id")
        if not iface_id:
            continue
        record = {
            "id": iface_id,
            "name": item.get("name") or iface_id,
            "type": item.get("type") or iface_id,
            "description": item.get("description", ""),
            "config_path": item.get("config_path", ""),
        }
        current = registry_get_item(merged, iface_id)
        if current:
            current.update(record)
        else:
            merged.append(record)
        existing_ids.add(iface_id)
    return merged


def seed_registry():
    with REGISTRY_LOCK:
        tasks = load_registry("tasks")
        csv_path = CONFIG.get("tasks_csv_path")
        csv_mode = (CONFIG.get("tasks_csv_mode") or "replace").lower()
        csv_autoload = bool(CONFIG.get("tasks_csv_autoload", False))
        if csv_autoload and csv_path:
            csv_tasks = load_tasks_from_csv(csv_path)
            if csv_tasks:
                if csv_mode == "merge":
                    tasks = merge_tasks(tasks, csv_tasks)
                else:
                    tasks = merge_tasks([], csv_tasks)
                write_registry("tasks", tasks)
        if not tasks:
            write_registry("tasks", default_tasks())
        else:
            changed, tasks = normalize_tasks(tasks)
            if changed:
                write_registry("tasks", tasks)
        interfaces = load_registry("interfaces")
        interfaces_csv_path = CONFIG.get("interfaces_csv_path")
        interfaces_csv_mode = (CONFIG.get("interfaces_csv_mode") or "replace").lower()
        interfaces_csv_autoload = bool(CONFIG.get("interfaces_csv_autoload", False))
        if interfaces_csv_autoload and interfaces_csv_path:
            csv_interfaces = load_interfaces_from_csv(interfaces_csv_path)
            if csv_interfaces:
                if interfaces_csv_mode == "merge":
                    interfaces = merge_interfaces(interfaces, csv_interfaces)
                else:
                    interfaces = merge_interfaces([], csv_interfaces)
                write_registry("interfaces", interfaces)
        if not interfaces:
            write_registry("interfaces", default_interfaces())
        users = load_registry("users")
        users_csv_path = CONFIG.get("users_csv_path")
        users_csv_mode = (CONFIG.get("users_csv_mode") or "replace").lower()
        users_csv_autoload = bool(CONFIG.get("users_csv_autoload", False))
        if users_csv_autoload and users_csv_path:
            csv_users = load_users_from_csv(users_csv_path)
            if csv_users:
                if users_csv_mode == "merge":
                    users = merge_users(users, csv_users)
                else:
                    users = merge_users([], csv_users)
                write_registry("users", users)
        if not isinstance(users, list):
            write_registry("users", [])
        else:
            changed, users = normalize_users(users)
            if changed:
                write_registry("users", users)


def load_config():
    cfg = {
        "data_root": "~/data",
        "python_bin": "python3",
        "collect_script": "",
        "collect_workdir": "",
        "collect_extra_args": [],
        "collect_shell_template": "",
        "collect_max_timesteps": -1,
        "replay_shell_template": "",
        "tasks_csv_autoload": True,
        "tasks_csv_path": "EXAMPLE.CSV",
        "tasks_csv_mode": "replace",
        "users_csv_autoload": True,
        "users_csv_path": "USERS_EXAMPLE.CSV",
        "users_csv_mode": "replace",
        "interfaces_csv_autoload": True,
        "interfaces_csv_path": "INTERFACES_EXAMPLE.CSV",
        "interfaces_csv_mode": "replace",
        "auto_start_stack": True,
        "require_sudo_password": False,
        "stack_enabled": True,
        "stack_workdir": "",
        "stack_clean_env": False,
        "stack_env_path": "",
        "stack_shell_login": True,
        "stack_python_bin": "",
        "stack_pythonpath": "",
        "stack_pythonpath_auto": False,
        "stack_pythonpath_auto_paths": [],
        "roscore_cmd": "",
        "arm_dep_check_cmd": "",
        "arm_dep_check_required": False,
        "arm_pre_cmd": "",
        "arm_launch_cmd": "",
        "camera_launch_cmd": "",
        "camera_pre_cmd": "",
        "camera_cleanup_nodes": ["/camera_f/camera", "/camera_l/camera", "/camera_r/camera"],
        "camera_cleanup_process_patterns": ["astra_camera", "ob_camera", "multi_camera"],
        "camera_cleanup_retries": 2,
        "camera_cleanup_delay": 1,
        "camera_cleanup_required": True,
        "camera_cleanup_use_sudo": True,
        "camera_cleanup_extra_cmd": "",
        "camera_cleanup_skip_if_topics_present": False,
        "camera_cleanup_skip_topics": [],
        "rosnode_list_cmd": "source /opt/ros/noetic/setup.bash && rosnode list",
        "topic_check_cmd": "source /opt/ros/noetic/setup.bash && rostopic list",
        "topic_check_on_start": True,
        "topic_echo_cmd": "source /opt/ros/noetic/setup.bash && timeout {timeout}s rostopic echo -n 1 {topic}",
        "topic_echo_timeout": 2,
        "require_topic_messages": True,
        "topic_data_ignore": [],
        "roscore_check_cmd": "",
        "topic_info_cmd": "source /opt/ros/noetic/setup.bash && timeout {timeout}s rostopic info {topic}",
        "topic_info_timeout": 2,
        "rosnode_kill_cmd": "source /opt/ros/noetic/setup.bash && rosnode kill {nodes}",
        "required_topics": [],
        "optional_topics": [],
        "master_topics": ["/master/joint_left", "/master/joint_right"],
        "auto_restart_master": True,
        "master_restart_retries": 1,
        "master_restart_delay": 2,
        "topic_check_retries": 1,
        "topic_check_delay": 0,
        "stack_start_delay": 0,
        "tail_lines": 200,
        "collect_shell_login": True,
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
        "tasks_csv_path",
        "users_csv_path",
        "interfaces_csv_path",
    ):
        value = cfg.get(path_key)
        if value:
            path_value = Path(value).expanduser()
            if path_key.endswith("_csv_path") and not path_value.is_absolute():
                path_value = APP_ROOT / path_value
            cfg[path_key] = str(path_value)
    return cfg


CONFIG = load_config()
BASE_CONFIG = dict(CONFIG)
seed_registry()

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
    "master_status": {
        "topics": [],
        "missing": [],
        "missing_data": [],
        "last_check": None,
        "error": None,
    },
    "camera_cleanup_status": {
        "killed_nodes": [],
        "killed_processes": [],
        "remaining_nodes": [],
        "remaining_processes": {},
        "last_run": None,
        "error": None,
    },
}


def apply_config_overrides(overrides):
    if not overrides:
        return
    CONFIG.clear()
    CONFIG.update(BASE_CONFIG)
    CONFIG.update(overrides)
    for path_key in (
        "data_root",
        "collect_script",
        "collect_workdir",
        "stack_workdir",
        "tasks_csv_path",
        "users_csv_path",
        "interfaces_csv_path",
    ):
        value = CONFIG.get(path_key)
        if value:
            path_value = Path(value).expanduser()
            if path_key.endswith("_csv_path") and not path_value.is_absolute():
                path_value = APP_ROOT / path_value
            CONFIG[path_key] = str(path_value)
    global DATA_ROOT, TAIL_LINES
    DATA_ROOT = expand_path(CONFIG["data_root"])
    TAIL_LINES = int(CONFIG.get("tail_lines", 200))


def load_interface_config(interface):
    cfg_path = (interface or {}).get("config_path") or ""
    if not cfg_path:
        return {}
    path = Path(cfg_path)
    if not path.is_absolute():
        path = APP_ROOT / path
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

SUDO_PASSWORD = None
SUDO_LOCK = threading.Lock()


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


def append_episode_log(data):
    ensure_registry_dir()
    path = REGISTRY_DIR / "episodes.jsonl"
    with REGISTRY_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")


def set_sudo_password(value):
    global SUDO_PASSWORD
    with SUDO_LOCK:
        SUDO_PASSWORD = value if value else None


def get_sudo_password():
    with SUDO_LOCK:
        return SUDO_PASSWORD


def build_env(clean=False):
    env = os.environ.copy()
    if clean:
        for key in list(env.keys()):
            if key.startswith("CONDA"):
                env.pop(key, None)
        for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
            env.pop(key, None)
        env["PATH"] = CONFIG.get("stack_env_path") or (
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        )
    sudo_pw = get_sudo_password()
    if sudo_pw:
        env["SUDO_PASSWORD"] = sudo_pw
    return env


def build_stack_env():
    env = build_env(clean=bool(CONFIG.get("stack_clean_env", False)))
    python_bin = CONFIG.get("stack_python_bin") or ""
    if python_bin:
        python_bin = expand_path(python_bin)
        python_dir = str(Path(python_bin).parent)
        env["PATH"] = f"{python_dir}:{env.get('PATH', '')}"
    pythonpaths = []
    explicit = CONFIG.get("stack_pythonpath") or ""
    if explicit:
        for part in explicit.split(":"):
            part = part.strip()
            if not part:
                continue
            path = expand_path(part)
            if Path(path).exists():
                pythonpaths.append(path)
    auto_enabled = bool(CONFIG.get("stack_pythonpath_auto", False))
    if auto_enabled and not pythonpaths:
        for item in CONFIG.get("stack_pythonpath_auto_paths", []) or []:
            if not item:
                continue
            path = expand_path(item)
            if Path(path).exists():
                pythonpaths.append(path)
    if pythonpaths:
        current = env.get("PYTHONPATH", "")
        combined = ":".join(pythonpaths + ([current] if current else []))
        env["PYTHONPATH"] = combined
    return env


def shell_args(cmd, login):
    return ["bash", "-lc" if login else "-c", cmd]


def run_shell(cmd, timeout=None, input_text=None, env=None, login=None):
    use_login = bool(CONFIG.get("stack_shell_login", True)) if login is None else login
    try:
        return subprocess.run(
            shell_args(cmd, use_login),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            env=env or build_env(),
            input=input_text,
        )
    except Exception:
        return None


def stack_shell_args(cmd):
    return shell_args(cmd, bool(CONFIG.get("stack_shell_login", True)))


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
            max_timesteps=CONFIG.get("collect_max_timesteps", ""),
        )
        use_login = bool(
            CONFIG.get("collect_shell_login", CONFIG.get("stack_shell_login", True))
        )
        return shell_args(cmd, use_login)
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
    max_steps = CONFIG.get("collect_max_timesteps", None)
    if max_steps is not None and str(max_steps) != "":
        cmd.extend(["--max_timesteps", str(max_steps)])
    extra = CONFIG.get("collect_extra_args") or []
    cmd.extend(extra)
    return cmd


class EpisodeRunner:
    def __init__(self):
        self.process = None
        self.thread = None

    def start(
        self, cmd, workdir, log_path, meta_dir, dataset_dir, episode_idx, requested_at=None
    ):
        env = os.environ.copy()
        ensure_dir(log_path.parent)
        log_file = log_path.open("w", encoding="utf-8")
        start_ts = time.time()
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
        add_log_line(f"[info] collector_process_started pid={proc.pid}")
        recording_logged = False

        def _reader():
            with log_file:
                for line in proc.stdout:
                    line = line.rstrip()
                    with STATE_LOCK:
                        STATE["last_log"].append(line)
                    nonlocal recording_logged
                    if (
                        not recording_logged
                        and "STATUS: RECORDING" in line
                    ):
                        base = requested_at if requested_at is not None else start_ts
                        elapsed = max(0.0, time.time() - base)
                        add_log_line(f"[info] collector_recording_after {elapsed:.2f}s")
                        recording_logged = True
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
            append_episode_log(
                {
                    "event": "end",
                    "timestamp": now_iso(),
                    "interface_id": STATE.get("session", {}).get("interface_id"),
                    "task_id": STATE.get("session", {}).get("task_id"),
                    "user_id": STATE.get("session", {}).get("user_id"),
                    "episode_id": episode_idx,
                    "exit_code": proc.returncode,
                }
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

    def start(self, name, cmd, workdir, log_path, env=None):
        if name in self.processes and self.processes[name].poll() is None:
            return False
        ensure_dir(log_path.parent)
        log_file = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            stack_shell_args(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=workdir or None,
            text=True,
            bufsize=1,
            env=env or build_env(),
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

    def stop(self, name):
        proc = self.processes.get(name)
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGINT)
                return True
            except Exception:
                return False
        return False


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
    stack_env = build_stack_env()
    require_sudo = bool(CONFIG.get("require_sudo_password", False))
    if require_sudo and not get_sudo_password():
        add_stack_log_line("[error] sudo_password_missing")
        return False, "sudo_password_missing"

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
            started = STACK.start(name, cmd, workdir, log_path, env=stack_env)
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
    dep_cmd = CONFIG.get("arm_dep_check_cmd") or ""
    dep_required = bool(CONFIG.get("arm_dep_check_required", False))
    if dep_cmd:
        dep_result = run_shell(dep_cmd, timeout=10, env=stack_env)
        if dep_result is None:
            add_stack_log_line("[error] arm_dep_check_failed: run_error")
            if dep_required:
                return False, "arm_dep_check_failed"
        elif dep_result.returncode != 0:
            add_stack_log_line("[error] arm_dep_check_failed")
            if dep_result.stdout.strip():
                add_stack_log_line(
                    f"[error] arm_dep_check_stdout: {dep_result.stdout.strip()}"
                )
            if dep_result.stderr.strip():
                add_stack_log_line(
                    f"[error] arm_dep_check_stderr: {dep_result.stderr.strip()}"
                )
            if dep_required:
                return False, "arm_dep_check_failed"
        else:
            add_stack_log_line("[info] arm_dep_check ok")
    arm_pre_cmd = CONFIG.get("arm_pre_cmd") or ""
    if arm_pre_cmd:
        result = run_shell(arm_pre_cmd, timeout=30, env=stack_env)
        if result is None:
            add_stack_log_line("[warn] arm_pre_cmd failed to run")
        else:
            if result.returncode != 0:
                add_stack_log_line(
                    f"[warn] arm_pre_cmd failed: {result.stderr.strip() or result.stdout.strip()}"
                )
            else:
                add_stack_log_line("[info] arm_pre_cmd executed")
    _start_named("arm")
    if delay > 0:
        time.sleep(delay)
    if not cleanup_camera():
        add_stack_log_line("[error] camera_cleanup_failed")
        return False, "camera_cleanup_failed"
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
            stack_shell_args(cmd),
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
                stack_shell_args(cmd),
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
                ignore = set(CONFIG.get("topic_data_ignore") or [])
                for topic in required:
                    if topic not in present:
                        continue
                    if topic in ignore:
                        continue
                    ok, _ = topic_has_data(topic, timeout)
                    if not ok:
                        missing_data.append(topic)
                for topic in optional:
                    if topic not in present:
                        continue
                    if topic in ignore:
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


def get_publishers(topic):
    cmd_tpl = CONFIG.get("topic_info_cmd")
    timeout = int(CONFIG.get("topic_info_timeout", 2) or 2)
    if not cmd_tpl:
        return []
    cmd = cmd_tpl.format(topic=topic, timeout=timeout)
    try:
        result = subprocess.run(
            stack_shell_args(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout + 1,
            check=False,
        )
        output = result.stdout.splitlines()
        publishers = []
        capture = False
        for line in output:
            line = line.strip()
            if line.startswith("Publishers:"):
                capture = True
                continue
            if capture:
                if not line or line.startswith("Subscribers:"):
                    break
                if line.startswith("*"):
                    publishers.append(line.lstrip("* ").strip())
        return publishers
    except Exception:
        return []


def kill_nodes(nodes):
    if not nodes:
        return False
    cmd_tpl = CONFIG.get("rosnode_kill_cmd")
    if not cmd_tpl:
        return False
    joined = " ".join(nodes)
    cmd = cmd_tpl.format(nodes=joined)
    try:
        subprocess.run(stack_shell_args(cmd), check=False)
        return True
    except Exception:
        return False


def restart_arm_process(session):
    cmd = CONFIG.get("arm_launch_cmd")
    if not cmd:
        return False
    workdir = CONFIG.get("stack_workdir") or None
    logs_dir = stack_logs_dir(session)
    ensure_dir(logs_dir)
    STACK.stop("arm")
    time.sleep(1)
    with STATE_LOCK:
        STATE["stack_processes"]["arm"] = {
            "cmd": cmd,
            "running": True,
            "exit_code": None,
            "external": False,
        }
    log_path = logs_dir / "stack_arm.log"
    return STACK.start("arm", cmd, workdir, log_path)


def ensure_master_data():
    topics = CONFIG.get("master_topics") or []
    if not topics:
        return True
    timeout = int(CONFIG.get("topic_echo_timeout", 2) or 2)
    missing = []
    missing_data = []
    for topic in topics:
        ok, _ = topic_has_data(topic, timeout)
        if not ok:
            missing_data.append(topic)
    status = {
        "topics": topics,
        "missing": missing,
        "missing_data": missing_data,
        "last_check": now_iso(),
        "error": None,
    }
    with STATE_LOCK:
        STATE["master_status"] = status
    if not missing_data:
        return True
    if not CONFIG.get("auto_restart_master", False):
        return False
    retries = int(CONFIG.get("master_restart_retries", 1) or 1)
    delay = float(CONFIG.get("master_restart_delay", 0) or 0)
    for _ in range(retries):
        publishers = []
        for topic in topics:
            publishers.extend(get_publishers(topic))
        if publishers:
            kill_nodes(sorted(set(publishers)))
            add_log_line(f"[warn] master publishers killed: {', '.join(sorted(set(publishers)))}")
        session = STATE.get("session")
        restarted = restart_arm_process(session)
        if restarted:
            add_log_line("[info] arm process restarted for master recovery")
        if delay > 0:
            time.sleep(delay)
        missing_data = []
        for topic in topics:
            ok, _ = topic_has_data(topic, timeout)
            if not ok:
                missing_data.append(topic)
        if not missing_data:
            return True
    with STATE_LOCK:
        STATE["master_status"]["missing_data"] = missing_data
    return False


def roscore_is_running():
    cmd = CONFIG.get("roscore_check_cmd") or CONFIG.get("topic_check_cmd")
    if not cmd:
        return False
    try:
        result = subprocess.run(
            stack_shell_args(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def list_rostopics():
    cmd = CONFIG.get("topic_check_cmd")
    if not cmd:
        return []
    try:
        result = subprocess.run(
            stack_shell_args(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
            check=False,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("/")]
    except Exception:
        return []


def list_rosnodes():
    cmd = CONFIG.get("rosnode_list_cmd")
    if not cmd:
        return []
    try:
        result = subprocess.run(
            stack_shell_args(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
            check=False,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("/")]
    except Exception:
        return []


def list_pids(pattern):
    try:
        result = subprocess.run(
            stack_shell_args(f"pgrep -f {shlex.quote(pattern)}"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return [pid for pid in result.stdout.split() if pid.isdigit()]
        return []
    except Exception:
        return []


def cleanup_camera():
    pre_cmd = CONFIG.get("camera_pre_cmd")
    nodes = CONFIG.get("camera_cleanup_nodes") or []
    patterns = CONFIG.get("camera_cleanup_process_patterns") or []
    retries = int(CONFIG.get("camera_cleanup_retries", 1) or 1)
    delay = float(CONFIG.get("camera_cleanup_delay", 0) or 0)
    required = bool(CONFIG.get("camera_cleanup_required", False))
    use_sudo = bool(CONFIG.get("camera_cleanup_use_sudo", False))
    extra_cmd = CONFIG.get("camera_cleanup_extra_cmd") or ""
    skip_if_present = bool(CONFIG.get("camera_cleanup_skip_if_topics_present", False))
    skip_topics = CONFIG.get("camera_cleanup_skip_topics") or []

    killed_nodes = []
    killed_patterns = []
    remaining_nodes = []
    remaining_procs = {}
    last_error = None
    sudo_prefix = ""
    sudo_input = None
    base_env = build_stack_env()
    if use_sudo:
        if get_sudo_password():
            sudo_prefix = "sudo -S "
            sudo_input = f"{get_sudo_password()}\n"
        else:
            sudo_prefix = "sudo -n "

    if skip_if_present and skip_topics:
        present = set(list_rostopics())
        missing = [t for t in skip_topics if t not in present]
        if not missing:
            status = {
                "killed_nodes": [],
                "killed_processes": [],
                "remaining_nodes": [],
                "remaining_processes": {},
                "last_run": now_iso(),
                "error": None,
                "skipped": True,
                "skip_topics": skip_topics,
            }
            with STATE_LOCK:
                STATE["camera_cleanup_status"] = status
            add_stack_log_line("[info] camera cleanup skipped (topics present)")
            return True

    for attempt in range(retries):
        if pre_cmd:
            try:
                subprocess.run(
                    stack_shell_args(pre_cmd),
                    check=False,
                    env=base_env,
                )
                add_stack_log_line("[info] camera_pre_cmd executed")
            except Exception as exc:
                last_error = str(exc)
                add_stack_log_line(f"[warn] camera_pre_cmd failed: {exc}")

        current_nodes = list_rosnodes()
        to_kill = [n for n in current_nodes if n in nodes]
        if to_kill:
            if kill_nodes(to_kill):
                killed_nodes = to_kill
                add_stack_log_line(f"[info] killed camera nodes: {', '.join(to_kill)}")

        for pattern in patterns:
            try:
                subprocess.run(
                    stack_shell_args(f"{sudo_prefix}pkill -f {shlex.quote(pattern)}"),
                    check=False,
                    env=base_env,
                    input=sudo_input,
                    text=True,
                )
                killed_patterns.append(pattern)
            except Exception as exc:
                last_error = str(exc)

        if extra_cmd:
            try:
                subprocess.run(
                    stack_shell_args(f"{sudo_prefix}{extra_cmd}"),
                    check=False,
                    env=base_env,
                    input=sudo_input,
                    text=True,
                )
                add_stack_log_line("[info] camera_cleanup_extra_cmd executed")
            except Exception as exc:
                last_error = str(exc)

        if delay > 0:
            time.sleep(delay)

        current_nodes = list_rosnodes()
        remaining_nodes = [
            n
            for n in current_nodes
            if n in nodes or n.startswith("/camera_") or n.startswith("/camera/")
        ]
        remaining_procs = {}
        for pattern in patterns:
            pids = list_pids(pattern)
            if pids:
                remaining_procs[pattern] = pids

        if not remaining_nodes and not remaining_procs:
            break

    status = {
        "killed_nodes": killed_nodes,
        "killed_processes": killed_patterns,
        "remaining_nodes": remaining_nodes,
        "remaining_processes": remaining_procs,
        "last_run": now_iso(),
        "error": last_error,
    }
    with STATE_LOCK:
        STATE["camera_cleanup_status"] = status

    if remaining_nodes or remaining_procs:
        add_stack_log_line(
            f"[warn] camera cleanup remaining nodes: {', '.join(remaining_nodes) if remaining_nodes else '-'}"
        )
        if remaining_procs:
            add_stack_log_line(f"[warn] camera cleanup remaining procs: {remaining_procs}")
        return not required

    add_stack_log_line("[info] camera cleanup ok")
    return True

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
            "master_status": STATE["master_status"],
            "camera_cleanup_status": STATE["camera_cleanup_status"],
        }
    data["data_root"] = DATA_ROOT
    data["collect_configured"] = bool(
        CONFIG.get("collect_shell_template") or CONFIG.get("collect_script")
    )
    data["stack_enabled"] = bool(CONFIG.get("stack_enabled", True))
    data["sudo_ready"] = bool(get_sudo_password())
    return jsonify(data)


@app.route("/api/interfaces", methods=["GET"])
def api_interfaces():
    interfaces = load_registry("interfaces")
    return jsonify({"interfaces": interfaces})


@app.route("/api/users", methods=["GET"])
def api_users():
    users = load_registry("users")
    users_sorted = sorted(users, key=lambda x: x.get("name", ""))
    return jsonify({"users": users_sorted})


@app.route("/api/users", methods=["POST"])
def api_users_add():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "invalid_name"}), 400
    with REGISTRY_LOCK:
        users = load_registry("users")
        existing = next((u for u in users if u.get("name") == name), None)
        if existing:
            return jsonify({"ok": True, "user": existing})
        user_id = generate_id(name, {u.get("id") for u in users})
        user = {"id": user_id, "name": name}
        users.append(user)
        write_registry("users", users)
    return jsonify({"ok": True, "user": user})


@app.route("/api/users/import", methods=["POST"])
def api_users_import():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []
    mode = (payload.get("mode") or "merge").lower()
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "invalid_items"}), 400
    with REGISTRY_LOCK:
        users = [] if mode == "replace" else load_registry("users")
        existing_ids = {u.get("id") for u in users}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name:
                continue
            user_id = item.get("id") or generate_id(name, existing_ids)
            existing_ids.add(user_id)
            record = {"id": user_id, "name": name}
            for key, value in item.items():
                if key not in record:
                    record[key] = value
            existing = registry_get_item(users, user_id)
            if existing:
                existing.update(record)
            else:
                users.append(record)
        write_registry("users", users)
    return jsonify({"ok": True, "count": len(users)})


@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    tasks = load_registry("tasks")
    tasks_sorted = sorted(tasks, key=lambda x: x.get("name", ""))
    return jsonify({"tasks": tasks_sorted})


@app.route("/api/tasks", methods=["POST"])
def api_tasks_add():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "invalid_name"}), 400
    description = (payload.get("description") or "").strip()
    success = (payload.get("success_criteria") or "").strip()
    with REGISTRY_LOCK:
        tasks = load_registry("tasks")
        existing = next((t for t in tasks if t.get("name") == name), None)
        if existing:
            return jsonify({"ok": True, "task": existing})
        task_id = generate_id(name, {t.get("id") for t in tasks})
        task = {
            "id": task_id,
            "name": name,
            "description": description,
            "success_criteria": success,
        }
        tasks.append(task)
        write_registry("tasks", tasks)
    return jsonify({"ok": True, "task": task})


@app.route("/api/tasks/import", methods=["POST"])
def api_tasks_import():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []
    mode = (payload.get("mode") or "merge").lower()
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "invalid_items"}), 400
    with REGISTRY_LOCK:
        tasks = [] if mode == "replace" else load_registry("tasks")
        existing_ids = {t.get("id") for t in tasks}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name:
                continue
            task_id = item.get("id") or generate_id(name, existing_ids)
            existing_ids.add(task_id)
            record = {
                "id": task_id,
                "name": name,
                "description": item.get("description", ""),
                "success_criteria": item.get("success_criteria", ""),
            }
            existing = registry_get_item(tasks, task_id)
            if existing:
                existing.update(record)
            else:
                tasks.append(record)
        write_registry("tasks", tasks)
    return jsonify({"ok": True, "count": len(tasks)})


@app.route("/api/sudo", methods=["POST"])
def api_sudo():
    payload = request.get_json(silent=True) or {}
    password = payload.get("password")
    if isinstance(password, str):
        password = password.strip()
    else:
        password = ""
    set_sudo_password(password)
    return jsonify({"ok": True, "set": bool(password)})


@app.route("/api/session/start", methods=["POST"])
def api_session_start():
    payload = request.get_json(silent=True) or {}
    interface_id = sanitize_token(payload.get("interface_id")) or "aloha"
    user_id = sanitize_token(payload.get("user_id"))
    task_id = sanitize_token(payload.get("task_id"))

    users = load_registry("users")
    tasks = load_registry("tasks")
    interfaces = load_registry("interfaces")
    interface = registry_get_item(interfaces, interface_id)
    if not interface:
        return jsonify({"ok": False, "error": "invalid_interface"}), 400

    interface_config = load_interface_config(interface)
    apply_config_overrides(interface_config)

    if not user_id:
        user_name = (payload.get("user") or "").strip()
        if not user_name:
            return jsonify({"ok": False, "error": "invalid_user"}), 400
        existing = next((u for u in users if u.get("name") == user_name), None)
        if existing:
            user_id = existing.get("id")
        else:
            user_id = generate_id(user_name, {u.get("id") for u in users})
            users.append({"id": user_id, "name": user_name})
            write_registry("users", users)

    if not task_id:
        task_name = (payload.get("task") or "").strip()
        if not task_name:
            return jsonify({"ok": False, "error": "invalid_task"}), 400
        existing = next((t for t in tasks if t.get("name") == task_name), None)
        if existing:
            task_id = existing.get("id")
        else:
            task_id = generate_id(task_name, {t.get("id") for t in tasks})
            tasks.append(
                {
                    "id": task_id,
                    "name": task_name,
                    "description": payload.get("task_description", ""),
                    "success_criteria": payload.get("task_success", ""),
                }
            )
            write_registry("tasks", tasks)

    user = registry_get_item(users, user_id)
    task = registry_get_item(tasks, task_id)
    if not user or not task:
        return jsonify({"ok": False, "error": "invalid_user_or_task"}), 400

    dataset_dir, meta_dir, logs_dir = session_paths(user_id, task_id)
    ensure_dir(dataset_dir)
    ensure_dir(meta_dir)
    ensure_dir(logs_dir)
    episodes = scan_episode_indices(dataset_dir)
    next_episode = (episodes[-1] + 1) if episodes else 0
    session = {
        "interface_id": interface_id,
        "interface_name": interface.get("name"),
        "interface_config_path": interface.get("config_path") or "",
        "user_id": user_id,
        "user_name": user.get("name"),
        "task_id": task_id,
        "task_name": task.get("name"),
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
    request_ts = time.time()
    add_log_line("[info] episode_start_requested")
    if CONFIG.get("auto_start_stack", False) and CONFIG.get("stack_enabled", True):
        ok, err = ensure_stack_running()
        if not ok:
            add_log_line(f"[error] stack_start_failed: {err}")
            return jsonify({"ok": False, "error": err}), 400
        if CONFIG.get("topic_check_on_start", True):
            status = run_topic_check()
            with STATE_LOCK:
                STATE["topic_status"] = status
            missing_required = status.get("missing") or []
            missing_optional = status.get("missing_optional") or []
            missing_data = status.get("missing_data") or []
            missing_optional_data = status.get("missing_optional_data") or []
            master_topics = set(CONFIG.get("master_topics") or [])
            if missing_required:
                non_master_missing = [t for t in missing_required if t not in master_topics]
                if non_master_missing:
                    add_log_line(f"[error] topics_missing: {', '.join(non_master_missing)}")
                    if missing_optional:
                        add_log_line(
                            f"[warn] topics_missing_optional: {', '.join(missing_optional)}"
                        )
                    return jsonify({"ok": False, "error": "topics_missing"}), 400
                if not ensure_master_data():
                    add_log_line("[error] master_no_data_after_restart")
                    return jsonify({"ok": False, "error": "master_no_data"}), 400
                status = run_topic_check()
                with STATE_LOCK:
                    STATE["topic_status"] = status
                missing_required = status.get("missing") or []
                missing_data = status.get("missing_data") or []
            if missing_data:
                non_master_missing = [t for t in missing_data if t not in master_topics]
                if non_master_missing:
                    add_log_line(f"[error] topics_no_data: {', '.join(non_master_missing)}")
                    if missing_optional_data:
                        add_log_line(
                            f"[warn] topics_no_data_optional: {', '.join(missing_optional_data)}"
                        )
                    return jsonify({"ok": False, "error": "topics_no_data"}), 400
                if not ensure_master_data():
                    add_log_line("[error] master_no_data_after_restart")
                    return jsonify({"ok": False, "error": "master_no_data"}), 400
        else:
            add_log_line("[info] topic_check_skipped")
    dataset_dir = Path(session["dataset_dir"])
    dataset_root = dataset_dir.parent
    cmd = build_collect_command(
        dataset_root, session["task_id"], next_episode
    )
    if not cmd:
        add_log_line("[error] collect_not_configured")
        return jsonify({"ok": False, "error": "collect_not_configured"}), 400
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
    append_episode_log(
        {
            "event": "start",
            "timestamp": now_iso(),
            "interface_id": session.get("interface_id"),
            "task_id": session.get("task_id"),
            "user_id": session.get("user_id"),
            "episode_id": next_episode,
            "storage_path": str(dataset_dir),
            "storage_name": f"episode_{next_episode}",
        }
    )
    try:
        RUNNER.start(
            cmd,
            workdir,
            log_path,
            meta_dir,
            dataset_dir,
            next_episode,
            requested_at=request_ts,
        )
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
    with STATE_LOCK:
        session = STATE.get("session")
        current_episode = STATE.get("current_episode")
        running = STATE.get("running")
    if session and running and current_episode is not None:
        append_episode_log(
            {
                "event": "stop_requested",
                "timestamp": now_iso(),
                "interface_id": session.get("interface_id"),
                "task_id": session.get("task_id"),
                "user_id": session.get("user_id"),
                "episode_id": current_episode,
            }
        )
    stopped = RUNNER.stop()
    if not stopped:
        state_reset = False
        with STATE_LOCK:
            if STATE["running"] or STATE["current_episode"] is not None:
                STATE["running"] = False
                STATE["current_episode"] = None
                STATE["last_error"] = "no_running_process"
                state_reset = True
        if state_reset:
            add_log_line("[warn] stop called with no process; state reset")
            return jsonify({"ok": True, "note": "state_reset"})
        return jsonify({"ok": False, "error": "no_running_process"}), 409
    return jsonify({"ok": True, "note": "signal_sent"})


@app.route("/api/stack/start", methods=["POST"])
def api_stack_start():
    if not CONFIG.get("stack_enabled", True):
        return jsonify({"ok": False, "error": "stack_disabled"}), 400
    ok, err = ensure_stack_running()
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/stack/stop", methods=["POST"])
def api_stack_stop():
    if not CONFIG.get("stack_enabled", True):
        return jsonify({"ok": False, "error": "stack_disabled"}), 400
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


def cleanup_processes():
    try:
        RUNNER.stop()
    except Exception:
        pass
    try:
        STACK.stop_all()
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    atexit.register(cleanup_processes)
    def _handle_exit(signum, frame):
        cleanup_processes()
        raise SystemExit(0)
    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
