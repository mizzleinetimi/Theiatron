#!/usr/bin/env bash
# Fetch and normalize the 4 real traffic clips used by the Theiatron demo.
# All clips are from Pexels (free license, no attribution required).
# Downloads are pinned by URL + sha256; every clip is normalized to
# 1280x720 @ 30fps, max 60s, no audio, so all feeds advance in lockstep.
set -euo pipefail
cd "$(dirname "$0")/.."

RAW=videos/raw
OUT=videos
mkdir -p "$RAW" "$OUT"

# name | pexels page id | direct url | sha256
CLIPS=(
  "north|4791734|https://videos.pexels.com/video-files/4791734/4791734-hd_1920_1080_30fps.mp4|38b883019d5180a675c154ac065fd57596be92148dae613ed4ee247f0659d6b7"
  "south|18437773|https://videos.pexels.com/video-files/18437773/18437773-hd_1920_1080_50fps.mp4|dd152b56e1dd70cc32c1b904baff08c1e8a427853cc99d877db31202f9f72aca"
  "east|12781265|https://videos.pexels.com/video-files/12781265/12781265-hd_1920_1080_50fps.mp4|b0d06b4af6d62934c7cef89e1d43b33df1412caf33b28eaa705a5ed236444910"
  "west|12245334|https://videos.pexels.com/video-files/12245334/12245334-hd_1920_1080_60fps.mp4|e020f415315b403cfc7cc3e53257cf44cecacec18aa1234dbd1869103552bbb9"
)

for entry in "${CLIPS[@]}"; do
  IFS='|' read -r name id url sha <<<"$entry"
  raw="$RAW/pexels_${id}.mp4"
  if [[ ! -f "$raw" ]]; then
    echo "downloading $name (pexels $id)..."
    curl -fL --retry 3 -o "$raw" "$url" \
      || curl -fL --retry 3 -o "$raw" "https://www.pexels.com/download/video/${id}/"
  fi
  echo "$sha  $raw" | shasum -a 256 -c - || {
    echo "checksum mismatch for $raw (Pexels may have re-encoded; delete and retry)" >&2
    exit 1
  }
  out="$OUT/${name}.mp4"
  if [[ ! -f "$out" ]]; then
    echo "normalizing $name -> $out"
    ffmpeg -hide_banner -loglevel error -y -i "$raw" \
      -vf "scale=1280:720" -r 30 -t 60 -an -c:v libx264 -preset fast -crf 20 "$out"
  fi
  ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height,avg_frame_rate -show_entries format=duration \
    -of default=noprint_wrappers=1 "$out"
  echo "ok: $out"
done
echo "all clips ready."
