#!/usr/bin/env python3
import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path


def add_sdk_path(sdk_root=None):
    if sdk_root:
        path = Path(sdk_root).expanduser()
        if path.exists():
            sys.path.insert(0, str(path))
            return
    sdk_root = Path(__file__).resolve().parent / "third_party" / "pika_sdk"
    if sdk_root.exists():
        sys.path.insert(0, str(sdk_root))


def load_sense_class(sdk_root=None):
    add_sdk_path(sdk_root)
    try:
        from pika import sense as SenseClass

        return SenseClass
    except Exception:
        pass
    try:
        from pika.sense import Sense as SenseClass

        return SenseClass
    except Exception as exc:
        raise ImportError("pika SDK not found") from exc


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def now_ms():
    return int(time.time() * 1000)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="")
    parser.add_argument("--dataset_dir", default="")
    parser.add_argument("--task_name", default="")
    parser.add_argument("--episode_idx", type=int, default=0)
    parser.add_argument("--max_timesteps", type=int, default=-1)
    parser.add_argument("--sdk_root", default="")
    parser.add_argument("--root", default="")
    parser.add_argument("--task", default="")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--fisheye_index", type=int, default=0)
    parser.add_argument("--realsense_serial", default="")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--tracker_id", default="WM0")
    parser.add_argument("--require_pose", action="store_true")
    parser.add_argument("--pose_miss_limit", type=int, default=30)
    parser.add_argument("--pose_start_timeout", type=float, default=5.0)
    parser.add_argument("--no_fisheye", action="store_true")
    parser.add_argument("--no_realsense_color", action="store_true")
    parser.add_argument("--no_realsense_depth", action="store_true")
    parser.add_argument("--no_tracker", action="store_true")
    return parser.parse_args()


def resolve_dataset(args):
    dataset_dir = args.dataset_dir or args.root
    task_name = args.task_name or args.task
    if not dataset_dir or not task_name:
        raise ValueError("dataset_dir/root and task_name/task are required")
    base_dir = Path(dataset_dir).expanduser() / task_name
    episode_dir = base_dir / f"episode_{args.episode_idx}"
    episode_dir.mkdir(parents=True, exist_ok=True)
    return base_dir, episode_dir


def load_device_config(path):
    cfg_path = Path(path).expanduser()
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).resolve().parent / cfg_path
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, {}, {}
    if isinstance(data, dict):
        extras = dict(data)
        extras.pop("devices", None)
        extras.pop("defaults", None)
        return data.get("devices") or [], data.get("defaults") or {}, extras
    return [], {}, {}


def build_devices(args, devices=None, defaults=None):
    defaults = defaults or {}
    devices = devices or []
    if not devices:
        devices = [{}]
    output = []
    existing = set()
    for idx, item in enumerate(devices):
        merged = dict(defaults)
        merged.update(item or {})
        name = merged.get("name") or f"device_{idx}"
        if name in existing:
            name = f"{name}_{idx}"
        existing.add(name)
        output.append(
            {
                "name": name,
                "port": merged.get("port") or args.port,
                "fisheye_index": merged.get("fisheye_index", args.fisheye_index),
                "realsense_serial": merged.get("realsense_serial", args.realsense_serial),
                "width": merged.get("width", args.width),
                "height": merged.get("height", args.height),
                "fps": merged.get("fps", args.fps),
                "tracker_id": merged.get("tracker_id", args.tracker_id),
                "require_pose": merged.get("require_pose", args.require_pose),
                "pose_miss_limit": int(merged.get("pose_miss_limit", args.pose_miss_limit)),
                "pose_start_timeout": float(
                    merged.get("pose_start_timeout", args.pose_start_timeout)
                ),
                "enable_fisheye": merged.get("enable_fisheye", not args.no_fisheye),
                "enable_realsense_color": merged.get(
                    "enable_realsense_color", not args.no_realsense_color
                ),
                "enable_realsense_depth": merged.get(
                    "enable_realsense_depth", not args.no_realsense_depth
                ),
                "enable_tracker": merged.get("enable_tracker", not args.no_tracker),
            }
        )
    return output


def main():
    args = parse_args()
    try:
        base_dir, episode_dir = resolve_dataset(args)
    except ValueError as exc:
        print(f"[error] {exc}")
        return 1

    try:
        import cv2
        import numpy as np
    except Exception as exc:
        print(f"[error] missing dependencies: {exc}")
        return 1

    devices_cfg = []
    defaults_cfg = {}
    extras = {}
    if args.config:
        devices_cfg, defaults_cfg, extras = load_device_config(args.config)
    sdk_root = args.sdk_root or extras.get("sdk_root") or os.environ.get("PIKA_SDK_ROOT")
    SenseClass = load_sense_class(sdk_root)
    shared_sense_port = (extras.get("shared_sense_port") or "").strip()
    devices = build_devices(args, devices_cfg, defaults_cfg)
    if not devices:
        print("[error] no devices configured")
        return 1
    active = []
    fatal_error = None
    shared_sense = None
    shared_configured = False
    shared_cameras = {"fisheye": None, "realsense": None}
    if shared_sense_port:
        shared_sense = SenseClass(shared_sense_port)
        if not shared_sense.connect():
            print(f"[error] failed to connect shared Sense on {shared_sense_port}")
            return 1
    for device in devices:
        sense = shared_sense
        if not sense:
            sense = SenseClass(device["port"]) if device["port"] else SenseClass()
            if not sense.connect():
                print(f"[error] failed to connect Pika Sense on {device['port']}")
                continue
            sense.set_camera_param(device["width"], device["height"], device["fps"])
            if device["fisheye_index"] is not None:
                sense.set_fisheye_camera_index(device["fisheye_index"])
            if device["realsense_serial"]:
                sense.set_realsense_serial_number(device["realsense_serial"])
        elif not shared_configured:
            sense.set_camera_param(device["width"], device["height"], device["fps"])
            if device["fisheye_index"] is not None:
                sense.set_fisheye_camera_index(device["fisheye_index"])
            if device["realsense_serial"]:
                sense.set_realsense_serial_number(device["realsense_serial"])
            shared_configured = True

        if shared_sense:
            if not shared_configured:
                shared_configured = True
            if shared_cameras["fisheye"] is None:
                shared_cameras["fisheye"] = (
                    None if not device["enable_fisheye"] else sense.get_fisheye_camera()
                )
            if shared_cameras["realsense"] is None:
                if device["enable_realsense_color"] or device["enable_realsense_depth"]:
                    shared_cameras["realsense"] = sense.get_realsense_camera()
            fisheye_camera = shared_cameras["fisheye"]
            realsense_camera = shared_cameras["realsense"]
        else:
            fisheye_camera = (
                None if not device["enable_fisheye"] else sense.get_fisheye_camera()
            )
            realsense_camera = None
            if device["enable_realsense_color"] or device["enable_realsense_depth"]:
                realsense_camera = sense.get_realsense_camera()

        tracker_id = device["tracker_id"] if device["enable_tracker"] else ""
        tracker_devices = sense.get_tracker_devices() if tracker_id else []
        if tracker_id and tracker_id not in tracker_devices:
            print(
                f"[warn] tracker_id {tracker_id} not detected for {device['name']} ({device['port']}); "
                f"devices: {tracker_devices}"
            )
        require_pose = bool(device["require_pose"]) and bool(tracker_id)
        if require_pose and tracker_id:
            deadline = time.time() + max(0.0, device["pose_start_timeout"])
            while tracker_id not in tracker_devices and time.time() < deadline:
                time.sleep(0.2)
                tracker_devices = sense.get_tracker_devices() or []
            if tracker_id not in tracker_devices:
                fatal_error = (
                    f"required tracker {tracker_id} not detected for {device['name']} "
                    f"({device['port']})"
                )
                sense.disconnect()
                break

        device_dir = episode_dir / device["name"]
        frames_dir = device_dir / "frames"
        fisheye_dir = frames_dir / "fisheye"
        rs_color_dir = frames_dir / "realsense_color"
        rs_depth_dir = frames_dir / "realsense_depth"
        if fisheye_camera:
            fisheye_dir.mkdir(parents=True, exist_ok=True)
        if realsense_camera and device["enable_realsense_color"]:
            rs_color_dir.mkdir(parents=True, exist_ok=True)
        if realsense_camera and device["enable_realsense_depth"]:
            rs_depth_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "started_at": now_iso(),
            "started_at_ms": now_ms(),
            "port": shared_sense_port or device["port"],
            "fisheye_index": device["fisheye_index"],
            "realsense_serial": device["realsense_serial"],
            "width": device["width"],
            "height": device["height"],
            "fps": device["fps"],
            "tracker_id": tracker_id,
            "tracker_devices": tracker_devices,
            "shared_sense_port": shared_sense_port,
            "require_pose": require_pose,
            "pose_miss_limit": device["pose_miss_limit"],
            "pose_start_timeout": device["pose_start_timeout"],
        }
        device_dir.mkdir(parents=True, exist_ok=True)
        (device_dir / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        active.append(
            {
                "spec": device,
                "sense": sense,
                "fisheye": fisheye_camera,
                "realsense": realsense_camera,
                "tracker_id": tracker_id,
                "require_pose": require_pose,
                "pose_miss_limit": device["pose_miss_limit"],
                "miss_counts": {"pose": 0},
                "fail_counts": {"fisheye": 0, "rs_color": 0, "rs_depth": 0},
                "disabled": {
                    "fisheye": not bool(fisheye_camera),
                    "rs_color": not bool(realsense_camera and device["enable_realsense_color"]),
                    "rs_depth": not bool(realsense_camera and device["enable_realsense_depth"]),
                },
                "poses_path": device_dir / "poses.jsonl",
                "meta": meta,
                "dirs": {
                    "fisheye": fisheye_dir,
                    "rs_color": rs_color_dir,
                    "rs_depth": rs_depth_dir,
                },
            }
        )

    if fatal_error:
        for item in active:
            if not shared_sense or item["sense"] is not shared_sense:
                item["sense"].disconnect()
        if shared_sense:
            shared_sense.disconnect()
        print(f"[error] {fatal_error}")
        return 1

    if not active:
        print("[error] no devices connected")
        return 1

    root_meta = {
        "started_at": now_iso(),
        "started_at_ms": now_ms(),
        "devices": [item["spec"] for item in active],
    }
    (episode_dir / "meta.json").write_text(
        json.dumps(root_meta, indent=2), encoding="utf-8"
    )

    stop_flag = {"value": False}

    def _handle_stop(signum, frame):
        stop_flag["value"] = True

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    step = 0
    last_frame_time = time.time()
    sleep_target = 1.0 / max(1, args.fps)
    fail_limit = 30

    try:
        files = []
        for item in active:
            f = item["poses_path"].open("a", encoding="utf-8")
            files.append((item, f))
        try:
            while True:
                if stop_flag["value"]:
                    break
                if args.max_timesteps > 0 and step >= args.max_timesteps:
                    break

                timestamp = now_iso()
                timestamp_ms = now_ms()
                any_data = False
                batch = []
                for item, f in files:
                    record = {
                        "timestep": step,
                        "timestamp": timestamp,
                        "timestamp_ms": timestamp_ms,
                        "frames": {},
                        "pose": None,
                    }
                    has_data = False

                    fisheye_camera = item["fisheye"]
                    realsense_camera = item["realsense"]
                    tracker_id = item["tracker_id"]
                    dirs = item["dirs"]
                    spec = item["spec"]
                    fail_counts = item["fail_counts"]
                    disabled = item["disabled"]

                    if fisheye_camera and not disabled["fisheye"]:
                        ok, frame = fisheye_camera.get_frame()
                        if ok and frame is not None:
                            path = dirs["fisheye"] / f"{step:06d}.jpg"
                            cv2.imwrite(str(path), frame)
                            record["frames"]["fisheye"] = str(path.name)
                            has_data = True
                            fail_counts["fisheye"] = 0
                        else:
                            fail_counts["fisheye"] += 1
                            if fail_counts["fisheye"] >= fail_limit:
                                disabled["fisheye"] = True
                                print("[warn] fisheye unavailable; disabling stream")

                    if realsense_camera and spec["enable_realsense_color"] and not disabled["rs_color"]:
                        ok, frame = realsense_camera.get_color_frame()
                        if ok and frame is not None:
                            path = dirs["rs_color"] / f"{step:06d}.jpg"
                            cv2.imwrite(str(path), frame)
                            record["frames"]["realsense_color"] = str(path.name)
                            has_data = True
                            fail_counts["rs_color"] = 0
                        else:
                            fail_counts["rs_color"] += 1
                            if fail_counts["rs_color"] >= fail_limit:
                                disabled["rs_color"] = True
                                print("[warn] realsense color unavailable; disabling stream")

                    if realsense_camera and spec["enable_realsense_depth"] and not disabled["rs_depth"]:
                        ok, depth = realsense_camera.get_depth_frame()
                        if ok and depth is not None:
                            path = dirs["rs_depth"] / f"{step:06d}.npy"
                            np.save(str(path), depth)
                            record["frames"]["realsense_depth"] = str(path.name)
                            has_data = True
                            fail_counts["rs_depth"] = 0
                        else:
                            fail_counts["rs_depth"] += 1
                            if fail_counts["rs_depth"] >= fail_limit:
                                disabled["rs_depth"] = True
                                print("[warn] realsense depth unavailable; disabling stream")

                    if tracker_id:
                        pose = item["sense"].get_pose(tracker_id)
                        if pose:
                            record["pose"] = {
                                "position": list(pose.position),
                                "rotation": list(pose.rotation),
                            }
                            has_data = True
                            item["miss_counts"]["pose"] = 0
                        else:
                            item["miss_counts"]["pose"] += 1
                            if item["miss_counts"]["pose"] in (1, 30, 300):
                                print(
                                    f"[warn] no pose for {tracker_id} "
                                    f"({spec['name']} {spec['port']})"
                                )
                            if item["require_pose"] and item["miss_counts"]["pose"] >= item[
                                "pose_miss_limit"
                            ]:
                                fatal_error = (
                                    f"pose missing for {tracker_id} "
                                    f"({spec['name']} {spec['port']})"
                                )

                    batch.append((f, record, has_data))
                    if has_data:
                        any_data = True

                if fatal_error:
                    print(f"[error] {fatal_error}")
                    break

                if any_data:
                    for f, record, _ in batch:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        f.flush()
                    step += 1
                    print(f"Frame data: {step}")
                else:
                    time.sleep(0.01)

                now_t = time.time()
                elapsed = now_t - last_frame_time
                if elapsed < sleep_target:
                    time.sleep(sleep_target - elapsed)
                last_frame_time = time.time()
        finally:
            for _, f in files:
                f.close()

    finally:
        root_meta["ended_at"] = now_iso()
        root_meta["ended_at_ms"] = now_ms()
        (episode_dir / "meta.json").write_text(
            json.dumps(root_meta, indent=2), encoding="utf-8"
        )
        for item in active:
            item["meta"]["ended_at"] = now_iso()
            item["meta"]["ended_at_ms"] = now_ms()
            (item["poses_path"].parent / "meta.json").write_text(
                json.dumps(item["meta"], indent=2), encoding="utf-8"
            )
            if not shared_sense or item["sense"] is not shared_sense:
                item["sense"].disconnect()
        if shared_sense:
            shared_sense.disconnect()

    if step == 0:
        print("Save failure, no data collected.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
