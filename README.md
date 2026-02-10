# Episode Capture Console

Minimal web UI + backend to run data collection episodes and prepare replay payloads.

## What this system does

- Provides a web UI to select **Interface / User / Task** and start/stop episodes.
- Uses CSV files as the **source of truth** for users/tasks/interfaces (auto-loaded on startup).
- Stores trajectories in `data_root` and writes metadata logs for audit and CPH.
- Interface selection loads the **interface-specific config** (start commands, topics, etc.).

Current interfaces included: **Aloha**, **Direct**, and **Pika** (others can be added by CSV + JSON config).

## Quick start

1) Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Create `config.json` from the example and set the collector command.

```bash
cp config.example.json config.json
```

Edit `config.json`:

- `data_root`: where datasets live (default `~/data`)
- `collect_script`: full path to `collect_data.py`
- `collect_workdir`: directory to run the command from
- `collect_shell_template` (optional): a full shell command with placeholders
- `collect_max_timesteps`: max steps per episode (`-1` for no limit)
- `tasks_csv_path`: CSV file for tasks (default `EXAMPLE.CSV`)
- `tasks_csv_mode`: `replace` or `merge`
- `tasks_csv_autoload`: load CSV on startup
- `users_csv_path`: CSV file for users (default `USERS_EXAMPLE.CSV`)
- `users_csv_mode`: `replace` or `merge`
- `users_csv_autoload`: load CSV on startup
- `interfaces_csv_path`: CSV file for interfaces (default `INTERFACES_EXAMPLE.CSV`)
- `interfaces_csv_mode`: `replace` or `merge`
- `interfaces_csv_autoload`: load CSV on startup

`replace` means CSV is the only source; restarting overwrites manual edits. Use `merge` if you want to keep manual additions.

Example shell template matching the default AgileX image paths (conda + ROS):

```json
{
  "collect_max_timesteps": -1,
  "collect_shell_template": "source ~/miniconda3/etc/profile.d/conda.sh && conda activate aloha && source /opt/ros/noetic/setup.bash && source ~/cobot_magic/Piper_ros_private-ros-noetic/devel/setup.bash && python ~/cobot_magic/collect_data/collect_data.py --dataset_dir {dataset_dir} --task_name {task_name} --episode_idx {episode_idx} --max_timesteps {max_timesteps}"
}
```

System stack (auto-start ROS + arm + camera) is configurable via:

- `roscore_cmd`
- `arm_dep_check_cmd`
- `arm_dep_check_required`
- `arm_pre_cmd`
- `arm_launch_cmd`
- `camera_launch_cmd`
- `require_sudo_password`
- `stack_clean_env`
- `stack_env_path`
- `stack_shell_login`
- `stack_python_bin`
- `stack_pythonpath`
- `stack_pythonpath_auto`
- `stack_pythonpath_auto_paths`
- `topic_check_cmd`
- `topic_check_on_start`
- `required_topics`
- `optional_topics`
- `roscore_check_cmd`
- `topic_check_retries`
- `topic_check_delay`
- `camera_pre_cmd`
- `topic_echo_cmd`
- `topic_echo_timeout`
- `require_topic_messages`
- `topic_info_cmd`
- `topic_info_timeout`
- `rosnode_kill_cmd`
- `master_topics`
- `auto_restart_master`
- `master_restart_retries`
- `master_restart_delay`
- `collect_shell_login`
- `camera_cleanup_nodes`
- `camera_cleanup_process_patterns`
- `camera_cleanup_retries`
- `camera_cleanup_delay`
- `camera_cleanup_required`
- `camera_cleanup_use_sudo`
- `camera_cleanup_extra_cmd`
- `camera_cleanup_skip_if_topics_present`
- `camera_cleanup_skip_topics`
- `rosnode_list_cmd`
- `collect_max_timesteps`: max steps per episode (`-1` for no limit)

## Registry

The UI manages three registries stored under `registry/`:

- `users.json`
- `tasks.json`
- `interfaces.json`

Tasks, users, and interfaces can be auto-loaded from CSV on startup (default). See `EXAMPLE.CSV`, `USERS_EXAMPLE.CSV`, and `INTERFACES_EXAMPLE.CSV` for format and update `*_csv_path` if needed.

If an `id` column is missing, the system generates a stable slug ID from the name (so IDs stay consistent across restarts). For strict control, define `id` explicitly in the CSV.

The UI still allows adding users/tasks manually, but they will be overwritten on restart if the CSV mode is `replace`.

## Interface config mapping

`INTERFACES_EXAMPLE.CSV` includes a `config_path` column. When you select an interface in the UI and start a session:

- The JSON at `config_path` is loaded.
- Its keys override the base `config.json` for that session only.

Example `INTERFACES_EXAMPLE.CSV`:

```
id,name,type,description,config_path
aloha,Aloha,aloha,Aloha data collection interface.,interfaces/aloha.json
direct,Direct,direct,Direct ROS + collect.py workflow.,interfaces/direct.json
pika,Pika,pika,Pika Sense camera + Vive tracker collection.,interfaces/pika.json
```

## Storage layout

Metadata:

- `registry/users.json`: user list (`id`, `name`)
- `registry/tasks.json`: task list (`id`, `name`, `description`, `success_criteria`)
- `registry/interfaces.json`: interface list (`id`, `name`, `type`)
- `registry/episodes.jsonl`: global episode events (`start`, `stop_requested`, `end`)
 
Interface config:

- Each interface can reference a `config_path` (JSON) from `INTERFACES_EXAMPLE.CSV`.
- The selected interface's config is merged into the base config when a session starts.

Per-session data (created under `data_root`):

- `~/data/<user_id>/<task_id>/` (or your `data_root`)
  - `episode_<n>/` (raw trajectory data produced by `collect_data.py`)
  - `.meta/session.json` (session fields incl. `interface_id`, `user_id`, `task_id`)
  - `.meta/episodes.jsonl` (start/end timestamps per episode)
  - `.meta/logs/episode_<n>.log` (collector stdout)
  - `.meta/logs/stack_*.log` (ROS/launch logs)

`.meta` is hidden; use `ls -la` or `tree -a` to view it.

CPH can be computed from `.meta/episodes.jsonl` (per task) or `registry/episodes.jsonl` (global).

## Operator flow (Aloha)

1) Start the web UI (`python app.py --host 0.0.0.0 --port 8080`)
2) In the UI: select **Interface / User / Task**
3) Click **Start Session**
4) (Optional) click **Start Stack** to launch ROS + arm + camera
5) Click **Start Next Episode**
6) Click **Stop Episode** when done
7) Repeat for the next episode

## Operator flow (Pika)

1) Make sure the `pika_sdk` conda env has `opencv-python` and `numpy` (and SDK deps).
2) Connect Pika Sense device and cameras.
3) Start the web UI.
4) Select **Pika** interface, user, task.
5) Click **Start Session**, then **Start Next Episode**.

Pika data is saved under `episode_<n>/` with:

- `frames/fisheye/*.jpg`
- `frames/realsense_color/*.jpg`
- `frames/realsense_depth/*.npy`
- `poses.jsonl`
- `meta.json`

Pika devices are configured in `interfaces/pika_devices.json`:

- set `sdk_root` to your Pika SDK path (e.g. `/home/agilex/pika_ws/pika_sdk`) or export `PIKA_SDK_ROOT`
- set `port` for each Pika Sense device (`/dev/ttyUSB0`, `/dev/ttyUSB1`, ...)
- set `fisheye_index` and `realsense_serial`
- set `tracker_id` (`WM0`, `WM1`, ...)

## Multi-server deployment (3 machines)

Goal: same **users/tasks/interfaces**, separate **data**.

Recommended recipe:

1) Put CSVs on shared storage (or distribute identical copies):
   - `tasks.csv`, `users.csv`, `interfaces.csv`
2) Point each server to the same CSV paths in `config.json`.
3) Use different `data_root` per server (e.g. `/data/server1`, `/data/server2`, `/data/server3`).

This guarantees all machines show the same user/task/interface lists while storing trajectories separately.

If `auto_start_stack` is true, the server will attempt to start the stack before collecting.

Default `arm_dep_check_cmd`, `arm_pre_cmd`, `arm_launch_cmd` and `camera_launch_cmd` in `config.example.json` match the doc:

- Arm dep check: `python3 -c "import yaml"` in ROS env (fails if `python3-yaml` is missing).
- Arm pre: `sudo bash can_config.sh`
- Arm: `roslaunch piper start_ms_piper.launch mode:=0 auto_enable:=false`
- Camera: `roslaunch astra_camera multi_camera.launch`

If you use RealSense, replace `camera_launch_cmd` with:

```
source /opt/ros/noetic/setup.bash && cd ~/cobot_magic/camera_ws && source devel/setup.bash && roslaunch realsense2_camera multi_camera.launch
```

`optional_topics` contains depth/camera-info/base topics from the doc. Move them into `required_topics` if you want to block capture when they are missing.

If `require_sudo_password` is true, set the password in the UI before starting the stack. It is stored in memory only and not written to disk.

Use `stack_clean_env=true` to avoid inheriting the current shell environment; then choose the Python explicitly:

- System Python: leave `stack_python_bin` empty.
- Conda Python: set `stack_python_bin` (for example `/home/agilex/miniconda3/envs/aloha/bin/python3`).

If `piper_sdk` is missing, add its folder to `PYTHONPATH` for the stack:

- Set `stack_pythonpath` explicitly, or
- Enable `stack_pythonpath_auto` with `stack_pythonpath_auto_paths` to point at `~/cobot_magic/Piper_ros_private-ros-noetic/src`.

## Troubleshooting

Common issues tied to the doc steps:

- `ModuleNotFoundError: No module named 'yaml'` while starting arm
  - Cause: ROS Python missing `pyyaml`.
  - Fix:
    ```bash
    sudo apt-get update
    sudo apt-get install -y python3-yaml
    source /opt/ros/noetic/setup.bash
    which python3
    python3 -c "import yaml; print('yaml ok')"
    ```
  - If the error persists but `yaml ok` works in another terminal, ensure `stack_clean_env=true` so ROS launches with system Python.
- `ModuleNotFoundError: No module named 'piper_sdk'` while starting arm
  - Cause: `piper_sdk` is not visible to system Python used by ROS.
  - Fix (check where it lives):
    ```bash
    source /opt/ros/noetic/setup.bash
    python3 -c "import importlib.util as u; print(u.find_spec('piper_sdk'))"
    ```
  - If it exists under `~/cobot_magic/Piper_ros_private-ros-noetic/src/piper_sdk`, add:
    ```bash
    export PYTHONPATH=~/cobot_magic/Piper_ros_private-ros-noetic/src:$PYTHONPATH
    ```
    and re-run the stack, or bake it into `arm_launch_cmd`.
- `roscore cannot run as another roscore/master is already running`
  - Cause: A stale ROS master is already running.
  - Fix: kill the existing `roscore` or reboot as a last resort.
- Camera warnings like `... calibration file ... not found` or IR stream warnings
  - If `/camera_* /color/image_raw` is publishing, you can ignore IR/depth warnings when collecting color-only data.

Arm not moving to position (or master topics have no data):

- Check arm nodes are alive (`rosnode list` shows `piper_left`/`piper_right`).
- Check `/master/joint_left` and `/master/joint_right` have data (`rostopic hz ...`).
- For data collection, `mode:=0` is correct; for control/replay, the doc says `mode:=1 auto_enable:=true` is required.
- If CAN mapping is wrong or `can_config.sh` failed, joint data can be empty.

Why reboot sometimes “fixes” it:

- It resets ROS master, CAN device mapping, and USB camera locks that can leave nodes in a bad state.
- It clears stale processes that `roscore` refuses to overwrite.

If master topics have no data, the server can kill the master publishers and restart the arm launch (see `master_topics` and `auto_restart_master`).

## Operator flow (per doc)

This maps the doc's manual steps to the web UI:

1) Start the stack once at the beginning of a session.
   - UI: `Start Stack`
   - Runs: `roscore` (if not running), `can_config.sh`, `roslaunch piper ...`, `roslaunch astra_camera ...`
   - Keep this running; it owns the ROS nodes.
2) Start data collection after the stack is up.
   - UI: `Start Next Episode`
   - Runs: `collect_data.py` inside `conda activate aloha`
3) If you unplug CAN devices, re-run `can_config.sh` by stopping/starting the stack.
   - UI: `Stop Stack` then `Start Stack`

Open `http://<host>:8080` in the browser.

## One-click (conda)

```bash
chmod +x run_conda.sh
./run_conda.sh
```

Options:

- `ENV_NAME` (default `cobot_capture`)
- `PY_VER` (default `3.8`)
- `HOST` (default `0.0.0.0`)
- `PORT` (default `8080`)
- `COLLECT_DATA_DEST` (default `/home/agilex/cobot_magic/collect_data/collect_data.py`)
- `SKIP_COLLECT_COPY=1` to disable copying `collect_data.py`

## Notes

- Episodes are stored under `~/data/<user>/<task>/`.
- The UI does not run replay. It only selects and prepares a replay payload.
- To expose on the internet, put this behind a reverse proxy or use SSH port forwarding.
