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
python_bin=.venv/bin/python
observe_seconds=${THEIATRON_OBSERVE:-180}
evaluation_seconds=${THEIATRON_DURATION:-180}

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

exec "$python_bin" run_demo.py \
  --live-demo \
  --video "$video" \
  --observe "$observe_seconds" \
  --duration "$evaluation_seconds" \
  --road-model motion \
  "$@"
