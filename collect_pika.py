#!/usr/bin/env python3
import argparse
import json
import signal
import sys
import time
from pathlib import Path


def add_sdk_path():
    sdk_root = Path(__file__).resolve().parent / "third_party" / "pika_sdk"
    if sdk_root.exists():
        sys.path.insert(0, str(sdk_root))


def load_sense_class():
    add_sdk_path()
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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_dir", default="")
    parser.add_argument("--task_name", default="")
    parser.add_argument("--episode_idx", type=int, default=0)
    parser.add_argument("--max_timesteps", type=int, default=-1)
    parser.add_argument("--root", default="")
    parser.add_argument("--task", default="")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--fisheye_index", type=int, default=0)
    parser.add_argument("--realsense_serial", default="")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--tracker_id", default="WM0")
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

    SenseClass = load_sense_class()
    sense = SenseClass(args.port) if args.port else SenseClass()
    if not sense.connect():
        print("[error] failed to connect Pika Sense")
        return 1

    sense.set_camera_param(args.width, args.height, args.fps)
    if args.fisheye_index:
        sense.set_fisheye_camera_index(args.fisheye_index)
    if args.realsense_serial:
        sense.set_realsense_serial_number(args.realsense_serial)

    fisheye_camera = None if args.no_fisheye else sense.get_fisheye_camera()
    realsense_camera = None if (args.no_realsense_color and args.no_realsense_depth) else sense.get_realsense_camera()

    tracker_id = "" if args.no_tracker else (args.tracker_id or "")
    tracker_devices = []
    if tracker_id:
        tracker_devices = sense.get_tracker_devices()

    frames_dir = episode_dir / "frames"
    fisheye_dir = frames_dir / "fisheye"
    rs_color_dir = frames_dir / "realsense_color"
    rs_depth_dir = frames_dir / "realsense_depth"
    if fisheye_camera:
        fisheye_dir.mkdir(parents=True, exist_ok=True)
    if realsense_camera and not args.no_realsense_color:
        rs_color_dir.mkdir(parents=True, exist_ok=True)
    if realsense_camera and not args.no_realsense_depth:
        rs_depth_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "started_at": now_iso(),
        "port": args.port,
        "fisheye_index": args.fisheye_index,
        "realsense_serial": args.realsense_serial,
        "width": args.width,
        "height": args.height,
        "fps": args.fps,
        "tracker_id": tracker_id,
        "tracker_devices": tracker_devices,
    }
    (episode_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    stop_flag = {"value": False}

    def _handle_stop(signum, frame):
        stop_flag["value"] = True

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    poses_path = episode_dir / "poses.jsonl"
    step = 0
    last_frame_time = time.time()
    sleep_target = 1.0 / max(1, args.fps)

    try:
        with poses_path.open("a", encoding="utf-8") as f:
            while True:
                if stop_flag["value"]:
                    break
                if args.max_timesteps > 0 and step >= args.max_timesteps:
                    break

                timestamp = now_iso()
                record = {
                    "timestep": step,
                    "timestamp": timestamp,
                    "frames": {},
                    "pose": None,
                }

                has_data = False

                if fisheye_camera:
                    ok, frame = fisheye_camera.get_frame()
                    if ok and frame is not None:
                        path = fisheye_dir / f"{step:06d}.jpg"
                        cv2.imwrite(str(path), frame)
                        record["frames"]["fisheye"] = str(path.name)
                        has_data = True

                if realsense_camera and not args.no_realsense_color:
                    ok, frame = realsense_camera.get_color_frame()
                    if ok and frame is not None:
                        path = rs_color_dir / f"{step:06d}.jpg"
                        cv2.imwrite(str(path), frame)
                        record["frames"]["realsense_color"] = str(path.name)
                        has_data = True

                if realsense_camera and not args.no_realsense_depth:
                    ok, depth = realsense_camera.get_depth_frame()
                    if ok and depth is not None:
                        path = rs_depth_dir / f"{step:06d}.npy"
                        np.save(str(path), depth)
                        record["frames"]["realsense_depth"] = str(path.name)
                        has_data = True

                if tracker_id:
                    pose = sense.get_pose(tracker_id)
                    if pose:
                        record["pose"] = {
                            "position": list(pose.position),
                            "rotation": list(pose.rotation),
                        }
                        has_data = True

                if has_data:
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
        meta["ended_at"] = now_iso()
        (episode_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        sense.disconnect()

    if step == 0:
        print("Save failure, no data collected.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
