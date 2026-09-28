#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  printf 'Missing local Python environment. See docs/demo-operator-guide.md\n'
  read -r -p 'Press Return to close.'
  exit 1
fi
printf '\nInvestor demo: http://127.0.0.1:8766/workbench/demo.html\nKeep this terminal open during the demo. Press Control-C to stop.\n\n'
if curl --silent --fail http://127.0.0.1:8766/api/health >/dev/null; then
  printf 'A service is already listening on port 8766. Use the link above.\n'
  read -r -p 'Press Return to close this launcher (the service keeps running).'
else
  exec .venv/bin/python launcher_server.py --port 8766
fi
