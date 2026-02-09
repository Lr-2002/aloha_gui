#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${ENV_NAME:-cobot_capture}"
PY_VER="${PY_VER:-3.8}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
COLLECT_DATA_DEST="${COLLECT_DATA_DEST:-/home/agilex/cobot_magic/collect_data/collect_data.py}"
SKIP_COLLECT_COPY="${SKIP_COLLECT_COPY:-0}"

if command -v conda >/dev/null 2>&1; then
  CONDA_BASE="$(conda info --base)"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
  CONDA_BASE="$HOME/miniconda3"
else
  echo "conda not found. Install Miniconda/Anaconda first." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$CONDA_BASE/etc/profile.d/conda.sh"

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  conda create -y -n "$ENV_NAME" "python=$PY_VER"
fi

conda activate "$ENV_NAME"

pip install -r requirements.txt

if [ ! -f config.json ]; then
  cp config.example.json config.json
fi

if [ "$SKIP_COLLECT_COPY" != "1" ]; then
  if [ -f "collect_data.py" ]; then
    dest_dir="$(dirname "$COLLECT_DATA_DEST")"
    if [ -d "$dest_dir" ]; then
      cp "collect_data.py" "$COLLECT_DATA_DEST"
      echo "Copied collect_data.py -> $COLLECT_DATA_DEST"
    else
      echo "Skip copy: destination dir not found: $dest_dir" >&2
    fi
  else
    echo "Skip copy: collect_data.py not found in repo" >&2
  fi
fi

python app.py --host "$HOST" --port "$PORT"
