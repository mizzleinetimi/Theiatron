#!/usr/bin/env bash
# Open the local choose-a-video demo launcher.
set -euo pipefail
cd "$(dirname "$0")/.."

python_bin=.venv/bin/python
port=${THEIATRON_LAUNCHER_PORT:-8766}
base="http://127.0.0.1:$port"
log_path="/tmp/theiatron-launcher-$port.log"

if [[ ! -x "$python_bin" ]]; then
  echo "missing $python_bin; create the environment from README.md first" >&2
  exit 1
fi

if ! curl -fsS "$base/api/health" 2>/dev/null | grep -q 'theiatron-launcher'; then
  nohup "$python_bin" launcher_server.py --port "$port" >"$log_path" 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if curl -fsS "$base/api/health" 2>/dev/null | grep -q 'theiatron-launcher'; then
      break
    fi
    sleep 0.2
  done
fi

if ! curl -fsS "$base/api/health" 2>/dev/null | grep -q 'theiatron-launcher'; then
  echo "could not start the local launcher on port $port; see $log_path" >&2
  exit 1
fi

url="$base/launcher/"
echo "Theiatron launcher: $url"
if [[ "${THEIATRON_NO_OPEN:-0}" != "1" ]] && command -v open >/dev/null 2>&1; then
  open "$url"
fi
