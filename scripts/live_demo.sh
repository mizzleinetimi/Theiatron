#!/usr/bin/env bash
# One-command, offline-first stage demo on new intersection footage.
#
# Usage:
#   bash scripts/live_demo.sh path/to/intersection.mp4
#   THEIATRON_DURATION=90 bash scripts/live_demo.sh clip.mp4 --device mps
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -lt 1 ]]; then
  echo "usage: bash scripts/live_demo.sh path/to/intersection.mp4 [extra run_demo.py options]" >&2
  exit 2
fi

video=$1
shift
extra_args=("$@")
python_bin=.venv/bin/python
observe_seconds=${THEIATRON_OBSERVE:-180}
evaluation_seconds=${THEIATRON_DURATION:-180}
run_name=""

for ((i = 0; i < ${#extra_args[@]}; i++)); do
  if [[ "${extra_args[$i]}" == "--run-name" ]] && ((i + 1 < ${#extra_args[@]})); then
    run_name=${extra_args[$((i + 1))]}
    break
  elif [[ "${extra_args[$i]}" == --run-name=* ]]; then
    run_name=${extra_args[$i]#--run-name=}
    break
  fi
done
if [[ -z "$run_name" ]]; then
  run_name="live-$(date +%Y%m%d-%H%M%S)-$$"
  extra_args+=(--run-name "$run_name")
fi

if [[ ! -x "$python_bin" ]]; then
  echo "missing $python_bin; create the environment from README.md first" >&2
  exit 1
fi
if [[ ! -f "$video" ]]; then
  echo "video does not exist: $video" >&2
  exit 1
fi
if [[ ! -f yolo26n.pt ]]; then
  echo "missing yolo26n.pt; place the detector weights in the project root" >&2
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "missing ffmpeg; it is required for browser-compatible 3D footage" >&2
  exit 1
fi

"$python_bin" run_demo.py \
  --live-demo \
  --video "$video" \
  --observe "$observe_seconds" \
  --duration "$evaluation_seconds" \
  --road-model motion \
  "${extra_args[@]}"

manifest_path="out/$run_name/manifest.json"
if ! "$python_bin" -c \
  'import json,sys; raise SystemExit(0 if json.load(open(sys.argv[1]))["three_d"]["ready"] else 1)' \
  "$manifest_path"; then
  echo "run completed, but its 3D assets are not ready: $manifest_path" >&2
  exit 1
fi

viewer_port=${THEIATRON_VIEWER_PORT:-8765}
viewer_base="http://127.0.0.1:$viewer_port"
if ! curl -fsS "$viewer_base/viz/index.html" 2>/dev/null | grep -q "THEIATRON"; then
  nohup "$python_bin" -m http.server "$viewer_port" --bind 127.0.0.1 \
    >/tmp/theiatron-3d-server.log 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS "$viewer_base/viz/index.html" 2>/dev/null | grep -q "THEIATRON"; then
      break
    fi
    sleep 0.2
  done
fi
if ! curl -fsS "$viewer_base/viz/index.html" 2>/dev/null | grep -q "THEIATRON"; then
  echo "could not start the local 3D viewer on port $viewer_port" >&2
  exit 1
fi

viewer_url="$viewer_base/viz/index.html?run=out/$run_name"
echo "3D comparison: $viewer_url"
if [[ "${THEIATRON_NO_OPEN:-0}" != "1" ]] && command -v open >/dev/null 2>&1; then
  open "$viewer_url"
fi
