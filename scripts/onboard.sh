#!/usr/bin/env bash
# Compatibility wrapper for the unified live-video + 3D workflow:
#   bash scripts/onboard.sh path/to/footage.mp4 [duration_seconds]
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -lt 1 ]]; then
  echo "usage: bash scripts/onboard.sh path/to/footage.mp4 [duration_seconds]" >&2
  exit 2
fi

video=$1
duration=${2:-180}
THEIATRON_OBSERVE="$duration" THEIATRON_DURATION="$duration" \
  exec bash scripts/live_demo.sh "$video"
