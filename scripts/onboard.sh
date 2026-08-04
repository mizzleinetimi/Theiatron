#!/usr/bin/env bash
# Onboard ANY new intersection footage in one command:
#   bash scripts/onboard.sh path/to/raw_footage.mp4 [duration_seconds]
# normalize -> auto-calibrate -> full demo run -> 3D twin + A/B export.
set -euo pipefail
cd "$(dirname "$0")/.."

RAW="$1"
DUR="${2:-180}"
NAME="$(basename "${RAW%.*}")"
VID="videos/${NAME}_norm.mp4"
CFG="configs/${NAME}.yaml"
PY=.venv/bin/python

echo "== 1/5 normalizing -> $VID (720p/30fps, max ${DUR}s)"
ffmpeg -hide_banner -loglevel error -y -i "$RAW" \
  -vf "scale=1280:720" -r 30 -t "$DUR" -an -c:v libx264 -preset fast -crf 20 "$VID"

echo "== 2/5 creating config -> $CFG"
$PY - "$CFG" "$VID" <<'EOF'
import sys
from theiatron.config import AppConfig, ApproachConfig, save_config
cfg = AppConfig()
cfg.vision.imgsz = 640
# Seed with one approach so auto-calibrate knows which video to watch;
# it replaces the whole approaches list with what it learns.
cfg.approaches = [ApproachConfig(name="north", video=sys.argv[2], phase="NS")]
save_config(cfg, sys.argv[1])
EOF

echo "== 3/5 auto-calibrating (watching ${DUR}s of traffic)"
$PY run_demo.py --config "$CFG" --auto-calibrate --observe "$DUR" --headless

echo "== 4/5 full demo run (arrivals, motions, report, annotated video)"
$PY run_demo.py --config "$CFG" --duration "$DUR" --headless

echo "== 5/5 exporting 3D twin + A/B timeline"
$PY scripts/export_timeline.py out/events.json "$DUR" "$CFG"
ffmpeg -hide_banner -loglevel error -y -i out/annotated.mp4 \
  -vf "crop=1280:720:0:0" -c:v libx264 -preset veryfast -crf 23 \
  -movflags +faststart -an viz/footage.mp4

echo
echo "DONE. Review:"
echo "  calibration overlay : out/autocal_overlay.png  (check the lines!)"
echo "  refine a line       : $PY run_demo.py --config $CFG --calibrate <name>"
echo "  dashboard video     : out/annotated.mp4"
echo "  3D digital twin     : open viz/twin.html"
echo "  A/B comparison      : open viz/index.html"
echo "  report              : out/report.md"
