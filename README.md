# Episode Capture Console

Minimal web UI + backend to run data collection episodes and prepare replay payloads.

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

Example shell template matching the default AgileX image paths (conda + ROS):

```json
{
  "collect_shell_template": "source ~/miniconda3/etc/profile.d/conda.sh && conda activate aloha && source /opt/ros/noetic/setup.bash && source ~/cobot_magic/Piper_ros_private-ros-noetic/devel/setup.bash && python ~/cobot_magic/collect_data/collect_data.py --dataset_dir {dataset_dir} --task_name {task_name} --episode_idx {episode_idx}"
}
```

System stack (auto-start ROS + arm + camera) is configurable via:

- `roscore_cmd`
- `arm_launch_cmd`
- `camera_launch_cmd`
- `topic_check_cmd`
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
- `camera_cleanup_nodes`
- `camera_cleanup_process_patterns`
- `camera_cleanup_retries`
- `camera_cleanup_delay`
- `camera_cleanup_required`
- `camera_cleanup_use_sudo`
- `camera_cleanup_extra_cmd`
- `rosnode_list_cmd`

If `auto_start_stack` is true, the server will attempt to start the stack before collecting.

Default `arm_launch_cmd` and `camera_launch_cmd` in `config.example.json` match the doc:

- Arm: `bash can_config.sh` + `roslaunch piper start_ms_piper.launch mode:=0 auto_enable:=false`
- Camera: `roslaunch astra_camera multi_camera.launch`

If you use RealSense, replace `camera_launch_cmd` with:

```
source /opt/ros/noetic/setup.bash && cd ~/cobot_magic/camera_ws && source devel/setup.bash && roslaunch realsense2_camera multi_camera.launch
```

`optional_topics` contains depth/camera-info/base topics from the doc. Move them into `required_topics` if you want to block capture when they are missing.

If master topics have no data, the server can kill the master publishers and restart the arm launch (see `master_topics` and `auto_restart_master`).

3) Run the server

```bash
python app.py --host 0.0.0.0 --port 8080
```

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
