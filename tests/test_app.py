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
        app_module.DATA_ROOT = self.data_root
        app_module.seed_registry()
        self.client = app_module.app.test_client()
        self._reset_state()

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
