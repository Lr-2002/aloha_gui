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

Example shell template when you must source ROS:

```json
{
  "collect_shell_template": "source /opt/ros/noetic/setup.bash && source ~/cobot_magic/aloha-devel/devel/setup.bash && python ~/cobot_magic/aloha-devel/collect_data.py --dataset_dir {dataset_dir} --task_name {task_name} --episode_idx {episode_idx}"
}
```

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

## Notes

- Episodes are stored under `~/data/<user>/<task>/`.
- The UI does not run replay. It only selects and prepares a replay payload.
- To expose on the internet, put this behind a reverse proxy or use SSH port forwarding.
