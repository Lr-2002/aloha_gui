import copy
import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("SYNC_CONFIG_FROM_EXAMPLE", "0")

import app as app_module


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.registry_dir = pathlib.Path(self.tempdir.name) / "registry"
        self.data_root = pathlib.Path(self.tempdir.name) / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)

        app_module.REGISTRY_DIR = self.registry_dir
        self._config_backup = copy.deepcopy(app_module.CONFIG)
        self._base_backup = copy.deepcopy(app_module.BASE_CONFIG)
        base = copy.deepcopy(app_module.BASE_CONFIG)
        base["data_root"] = str(self.data_root)
        base["tasks_csv_autoload"] = False
        base["users_csv_autoload"] = False
        base["interfaces_csv_autoload"] = False
        app_module.BASE_CONFIG = base
        app_module.CONFIG.clear()
        app_module.CONFIG.update(base)
        app_module.DATA_ROOT = self.data_root
        app_module.seed_registry()
        self.client = app_module.app.test_client()
        self._reset_state()

    def tearDown(self):
        app_module.CONFIG.clear()
        app_module.CONFIG.update(self._config_backup)
        app_module.BASE_CONFIG = self._base_backup
        app_module.set_sudo_password(None)

    def _patch(self, obj, name, value):
        original = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)

    def _reset_state(self):
        with app_module.STATE_LOCK:
            app_module.STATE["session"] = None
            app_module.STATE["next_episode"] = 0
            app_module.STATE["current_episode"] = None
            app_module.STATE["running"] = False
            app_module.STATE["last_exit"] = None
            app_module.STATE["last_error"] = None
            app_module.STATE["last_log"].clear()
            app_module.STATE["episodes"] = []
            app_module.STATE["selected_episode"] = None
            app_module.STATE["last_replay"] = None
            app_module.STATE["stack_running"] = False
            app_module.STATE["stack_processes"] = {}

    def test_session_start_creates_user_and_task(self):
        resp = self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        session = data["session"]
        self.assertEqual(session["interface_id"], "aloha")
        self.assertEqual(session["user_name"], "alice")
        self.assertEqual(session["task_name"], "pickup")
        users = app_module.load_registry("users")
        tasks = app_module.load_registry("tasks")
        self.assertTrue(any(u.get("name") == "alice" for u in users))
        self.assertTrue(any(t.get("name") == "pickup" for t in tasks))
        self.assertTrue(pathlib.Path(session["dataset_dir"]).exists())

    def test_session_start_invalid_interface(self):
        resp = self.client.post(
            "/api/session/start",
            json={"interface_id": "bad", "user": "alice", "task": "pickup"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "invalid_interface")

    def test_episode_start_without_session(self):
        app_module.CONFIG["auto_start_stack"] = False
        app_module.CONFIG["collect_script"] = ""
        app_module.CONFIG["collect_shell_template"] = ""
        resp = self.client.post("/api/episode/start", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "no_session")

    def test_episode_start_not_configured(self):
        self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        app_module.CONFIG["auto_start_stack"] = False
        app_module.CONFIG["collect_script"] = ""
        app_module.CONFIG["collect_shell_template"] = ""
        resp = self.client.post("/api/episode/start", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "collect_not_configured")

    def test_episode_start_logs_start_event(self):
        resp = self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        session = resp.get_json()["session"]
        app_module.CONFIG["auto_start_stack"] = False
        app_module.CONFIG["collect_shell_template"] = "echo ok"
        app_module.CONFIG["collect_workdir"] = ""
        self._patch(app_module.RUNNER, "start", lambda *args, **kwargs: None)
        start_resp = self.client.post("/api/episode/start", json={})
        self.assertEqual(start_resp.status_code, 200)
        log_path = app_module.REGISTRY_DIR / "episodes.jsonl"
        entries = [json.loads(line) for line in log_path.read_text().splitlines()]
        start_entries = [e for e in entries if e.get("event") == "start"]
        self.assertTrue(start_entries)
        entry = start_entries[-1]
        self.assertEqual(entry.get("interface_id"), session.get("interface_id"))
        self.assertEqual(entry.get("task_id"), session.get("task_id"))
        self.assertEqual(entry.get("user_id"), session.get("user_id"))

    def test_episode_start_collect_workdir_missing(self):
        self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        app_module.CONFIG["auto_start_stack"] = False
        app_module.CONFIG["collect_shell_template"] = "echo ok"
        app_module.CONFIG["collect_workdir"] = str(self.data_root / "missing_dir")
        resp = self.client.post("/api/episode/start", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "collect_workdir_missing")

    def test_episode_stop_no_process_returns_409(self):
        resp = self.client.post("/api/episode/stop", json={})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["error"], "no_running_process")

    def test_episode_stop_resets_state_and_logs(self):
        resp = self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        session = resp.get_json()["session"]
        with app_module.STATE_LOCK:
            app_module.STATE["running"] = True
            app_module.STATE["current_episode"] = 0
        self._patch(app_module.RUNNER, "stop", lambda: False)
        stop_resp = self.client.post("/api/episode/stop", json={})
        self.assertEqual(stop_resp.status_code, 200)
        self.assertEqual(stop_resp.get_json()["note"], "state_reset")
        with app_module.STATE_LOCK:
            self.assertFalse(app_module.STATE["running"])
            self.assertIsNone(app_module.STATE["current_episode"])
        log_path = app_module.REGISTRY_DIR / "episodes.jsonl"
        entries = [json.loads(line) for line in log_path.read_text().splitlines()]
        stop_entries = [e for e in entries if e.get("event") == "stop_requested"]
        self.assertTrue(stop_entries)
        entry = stop_entries[-1]
        self.assertEqual(entry.get("interface_id"), session.get("interface_id"))
        self.assertEqual(entry.get("task_id"), session.get("task_id"))
        self.assertEqual(entry.get("user_id"), session.get("user_id"))

    def test_topic_check_skipped_when_disabled(self):
        self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        app_module.CONFIG["auto_start_stack"] = True
        app_module.CONFIG["topic_check_on_start"] = False
        app_module.CONFIG["collect_shell_template"] = "echo ok"
        app_module.CONFIG["collect_workdir"] = ""
        self._patch(app_module, "ensure_stack_running", lambda: (True, None))
        called = {"value": False}

        def _fake_topic_check():
            called["value"] = True
            return {}

        self._patch(app_module, "run_topic_check", _fake_topic_check)
        self._patch(app_module.RUNNER, "start", lambda *args, **kwargs: None)
        resp = self.client.post("/api/episode/start", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(called["value"])

    def test_topic_check_missing_non_master_blocks(self):
        self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        app_module.CONFIG["auto_start_stack"] = True
        app_module.CONFIG["topic_check_on_start"] = True
        app_module.CONFIG["collect_shell_template"] = "echo ok"
        self._patch(app_module, "ensure_stack_running", lambda: (True, None))
        self._patch(
            app_module,
            "run_topic_check",
            lambda: {
                "missing": ["/camera_f/color/image_raw"],
                "missing_optional": [],
                "missing_data": [],
                "missing_optional_data": [],
            },
        )
        self._patch(app_module.RUNNER, "start", lambda *args, **kwargs: None)
        resp = self.client.post("/api/episode/start", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "topics_missing")

    def test_topic_check_master_restart_fails(self):
        self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        app_module.CONFIG["auto_start_stack"] = True
        app_module.CONFIG["topic_check_on_start"] = True
        app_module.CONFIG["collect_shell_template"] = "echo ok"
        self._patch(app_module, "ensure_stack_running", lambda: (True, None))
        self._patch(
            app_module,
            "run_topic_check",
            lambda: {
                "missing": ["/master/joint_left"],
                "missing_optional": [],
                "missing_data": [],
                "missing_optional_data": [],
            },
        )
        self._patch(app_module, "ensure_master_data", lambda: False)
        resp = self.client.post("/api/episode/start", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "master_no_data")

    def test_stack_start_requires_sudo_password(self):
        app_module.CONFIG["roscore_cmd"] = "echo roscore"
        app_module.CONFIG["arm_launch_cmd"] = ""
        app_module.CONFIG["camera_launch_cmd"] = ""
        app_module.CONFIG["require_sudo_password"] = True
        resp = self.client.post("/api/stack/start", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "sudo_password_missing")

    def test_users_import(self):
        resp = self.client.post(
            "/api/users/import",
            json={"items": [{"name": "Bob"}], "mode": "merge"},
        )
        self.assertEqual(resp.status_code, 200)
        users = app_module.load_registry("users")
        self.assertTrue(any(u.get("name") == "Bob" for u in users))


if __name__ == "__main__":
    unittest.main()
