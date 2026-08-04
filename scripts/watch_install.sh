#!/usr/bin/env bash
# Live view of the Theiatron dependency install. Run in its own terminal:
#   bash ~/theiatron/scripts/watch_install.sh        (Ctrl-C to exit)
CACHE=~/.cache/uv
VENV=~/theiatron/.venv/lib/python3.12/site-packages
LOG=~/theiatron/install.log
prev=$(du -sk "$CACHE" 2>/dev/null | cut -f1)
while true; do
  clear
  now=$(du -sk "$CACHE" 2>/dev/null | cut -f1)
  rate=$(( (now - prev) / 2 ))
  prev=$now
  pkgs=$(ls "$VENV" 2>/dev/null | grep -vc dist-info)
  echo "=== Theiatron dependency install ==="
  echo
  echo "downloaded (uv cache): $((now / 1024)) MB   rate: ${rate} KB/s"
  echo "packages in venv:      ${pkgs:-0}  (0 until the very end - uv installs in one shot)"
  echo "installer running:     $(pgrep -f 'uv pip install' >/dev/null && echo YES || echo NO)"
  echo
  echo "--- installer log (last 8 lines) ---"
  tail -8 "$LOG" 2>/dev/null
  if ! pgrep -f 'uv pip install' >/dev/null; then
    echo
    if grep -q "Installed" "$LOG" 2>/dev/null; then
      echo ">>> DONE: $(grep Installed "$LOG" | tail -1)"
    else
      echo ">>> installer stopped - check $LOG"
    fi
    break
  fi
  sleep 2
done
