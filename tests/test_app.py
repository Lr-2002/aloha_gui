import copy
import json
import os
import pathlib
import tempfile
import time
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
        if hasattr(app_module, "_clear_replay_cache"):
            app_module._clear_replay_cache()

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

    def test_session_stop_without_session(self):
        resp = self.client.post("/api/session/stop", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["had_session"])

    def test_session_stop_dataarm_clears_state(self):
        dataset_dir = self.data_root / "wangxianhao" / "insert_lamp"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        with app_module.STATE_LOCK:
            app_module.STATE["session"] = {
                "interface_id": "dataarm",
                "dataset_dir": str(dataset_dir),
                "task_id": "insert_lamp",
                "user_id": "wangxianhao",
            }
            app_module.STATE["running"] = True
            app_module.STATE["current_episode"] = 1

        self._patch(app_module.SESSION_RUNNER, "is_running", lambda: True)
        self._patch(app_module.SESSION_RUNNER, "send_signal", lambda sig: True)
        self._patch(app_module.SESSION_RUNNER, "stop", lambda: True)

        resp = self.client.post("/api/session/stop", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["had_session"])
        self.assertTrue(data["stopped_recording"])
        self.assertTrue(data["stopped_gc_session"])
        with app_module.STATE_LOCK:
            self.assertIsNone(app_module.STATE["session"])
            self.assertFalse(app_module.STATE["running"])
            self.assertIsNone(app_module.STATE["current_episode"])

    def test_dataarm_fault_reason_pattern_match(self):
        app_module.CONFIG["dataarm_auto_stop_trigger_patterns"] = [
            "Deploy fail-fast triggered:",
            "Robot initialization failed",
            "Failed to send command: \\(5, 'Input/output error'\\)",
        ]
        reason = app_module._dataarm_fault_reason_from_log_line(
            "2026-03-06 12:00:00 | run_robot | ERROR | Deploy fail-fast triggered: camera:cam_top"
        )
        self.assertEqual(reason, "Deploy fail-fast triggered:")
        reason_servo = app_module._dataarm_fault_reason_from_log_line(
            "2026-03-06 17:31:47 | control.hardware.servo_usb_lib.servo_usb | ERROR | "
            "[servo=right_gripper arm=right_arm usb=/dev/dataarm_servo_right] "
            "Failed to send command: (5, 'Input/output error')"
        )
        self.assertEqual(reason_servo, "Failed to send command: \\(5, 'Input/output error'\\)")
        self.assertIsNone(app_module._dataarm_fault_reason_from_log_line("normal status line"))

    def test_request_dataarm_auto_stop_runs_sequence_and_stop(self):
        calls = []
        self._patch(app_module, "_run_dataarm_fault_lamp_sequence", lambda reason: calls.append(("lamp", reason)))
        self._patch(
            app_module,
            "_stop_session_internal",
            lambda source, reason: calls.append(("stop", source, reason)) or {"ok": True},
        )
        app_module.CONFIG["dataarm_auto_stop_on_fault"] = True
        ok = app_module._request_dataarm_auto_stop("log:Deploy fail-fast triggered:")
        self.assertTrue(ok)
        deadline = time.time() + 1.0
        while time.time() < deadline and len(calls) < 2:
            time.sleep(0.01)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "lamp")
        self.assertEqual(calls[1][0], "stop")
        self.assertEqual(calls[1][1], "auto_fault")

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

    def test_scan_episode_indices_dataarm_layout(self):
        dataset_dir = self.data_root / "wangxianhao" / "insert_lamp"
        s1 = dataset_dir / "lock_j2" / "trajectory" / "2026-03-04_14-42-25_805"
        s2 = dataset_dir / "lock_j2" / "trajectory" / "2026-03-04_14-44-20_878"
        s1.mkdir(parents=True, exist_ok=True)
        s2.mkdir(parents=True, exist_ok=True)
        (s1 / "session_manifest.json").write_text("{}", encoding="utf-8")
        (s2 / "session_manifest.json").write_text("{}", encoding="utf-8")

        episodes = app_module.scan_episode_indices(dataset_dir)
        self.assertEqual(episodes, [0, 1])

    def test_session_start_next_episode_from_dataarm_sessions(self):
        user_id = "wangxianhao"
        task_id = "insert_lamp"
        app_module.write_registry("users", [{"id": user_id, "name": user_id}])
        app_module.write_registry(
            "tasks",
            [
                {
                    "id": task_id,
                    "name": task_id,
                    "description": "",
                    "success_criteria": "",
                }
            ],
        )

        dataset_dir = self.data_root / user_id / task_id
        for idx in range(3):
            session_dir = dataset_dir / "lock_j2" / "trajectory" / f"2026-03-04_14-4{idx}-00_000"
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "session_manifest.json").write_text("{}", encoding="utf-8")

        resp = self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user_id": user_id, "task_id": task_id},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["next_episode"], 3)

    def _write_fake_jpeg(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Minimal JPEG SOI/EOI bytes for endpoint testing.
        path.write_bytes(b"\xff\xd8\xff\xd9")

    def test_replay_preview_three_camera_sync(self):
        start_resp = self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        self.assertEqual(start_resp.status_code, 200)
        dataset_dir = pathlib.Path(start_resp.get_json()["session"]["dataset_dir"])
        episode_dir = dataset_dir / "episode_0"
        videos_dir = episode_dir / "videos"
        for cam in ("cam_left", "cam_right", "cam_top"):
            (videos_dir / cam).mkdir(parents=True, exist_ok=True)
        self._write_fake_jpeg(videos_dir / "cam_left" / "l0.jpg")
        self._write_fake_jpeg(videos_dir / "cam_left" / "l1.jpg")
        self._write_fake_jpeg(videos_dir / "cam_right" / "r0.jpg")
        self._write_fake_jpeg(videos_dir / "cam_right" / "r1.jpg")
        self._write_fake_jpeg(videos_dir / "cam_top" / "t0.jpg")
        self._write_fake_jpeg(videos_dir / "cam_top" / "t1.jpg")
        metadata = {
            "timestamp_unit": "ms",
            "camera_names": ["cam_left", "cam_right", "cam_top"],
            "anchor_camera": "cam_left",
            "cameras": {
                "cam_left": {
                    "frames": [
                        {"filename": "l0.jpg", "timestamp_ms": 1000},
                        {"filename": "l1.jpg", "timestamp_ms": 1040},
                    ]
                },
                "cam_right": {
                    "frames": [
                        {"filename": "r0.jpg", "timestamp_ms": 1003},
                        {"filename": "r1.jpg", "timestamp_ms": 1042},
                    ]
                },
                "cam_top": {
                    "frames": [
                        {"filename": "t0.jpg", "timestamp_ms": 1002},
                        {"filename": "t1.jpg", "timestamp_ms": 1041},
                    ]
                },
            },
        }
        (episode_dir / "camera_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        resp = self.client.post("/api/replay/preview", json={"episode": 0})
        self.assertEqual(resp.status_code, 200)
        preview = resp.get_json()["preview"]
        self.assertEqual(preview["episode"], 0)
        self.assertEqual(preview["anchor_camera"], "cam_left")
        self.assertEqual(preview["frame_count"], 2)
        self.assertEqual(preview["camera_names"], ["cam_left", "cam_right", "cam_top"])
        self.assertEqual(len(preview["timeline_ms"]), 2)
        self.assertIn("cam_right", preview["timeline_to_frame"])

    def test_replay_frame_endpoint_returns_image(self):
        start_resp = self.client.post(
            "/api/session/start",
            json={"interface_id": "aloha", "user": "alice", "task": "pickup"},
        )
        self.assertEqual(start_resp.status_code, 200)
        dataset_dir = pathlib.Path(start_resp.get_json()["session"]["dataset_dir"])
        episode_dir = dataset_dir / "episode_0"
        frame_path = episode_dir / "videos" / "cam_left" / "l0.jpg"
        self._write_fake_jpeg(frame_path)
        metadata = {
            "timestamp_unit": "ms",
            "camera_names": ["cam_left"],
            "anchor_camera": "cam_left",
            "cameras": {
                "cam_left": {"frames": [{"filename": "l0.jpg", "timestamp_ms": 1000}]}
            },
        }
        (episode_dir / "camera_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        preview_resp = self.client.post("/api/replay/preview", json={"episode": 0})
        self.assertEqual(preview_resp.status_code, 200)

        frame_resp = self.client.get("/api/replay/frame?episode=0&camera=cam_left&frame_idx=0")
        self.assertEqual(frame_resp.status_code, 200)
        self.assertTrue(frame_resp.data.startswith(b"\xff\xd8"))


if __name__ == "__main__":
    unittest.main()
