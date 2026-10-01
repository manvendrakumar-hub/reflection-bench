#!/usr/bin/env bash
# Reflection Bench v2 - full pipeline, offline. No LLM, no browser, no network
# except the Lenskart fetch step (skip it if you already have the images).
#
#   ./run_offline.sh reflect        # just render whatever is in "Remaining PID"
#   ./run_offline.sh fetch          # download plates for PIDs in the sheet
#   ./run_offline.sh all            # fetch then reflect
#   ./run_offline.sh serve          # start the HTTP service on :8080
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-$(command -v python3)}"
if ! "$PY" -c 'import numpy, PIL' 2>/dev/null; then
  echo "ERROR: $PY lacks numpy/pillow."
  echo "  pip install -r requirements.txt     (or set PY=/path/to/python3)"
  exit 1
fi
WORKERS="${WORKERS:-$("$PY" -c 'import os;print(os.cpu_count() or 4)')}"

case "${1:-help}" in
  fetch)   "$PY" fetch_pids.py --limit 100000 --workers 4 ;;
  reflect) "$PY" batch_reflect.py --all --workers "$WORKERS" ;;
  serve)   "$PY" reflect_server.py --port "${PORT:-8080}" ;;
  all)     "$PY" fetch_pids.py --limit 100000 --workers 4
           "$PY" batch_reflect.py --all --workers "$WORKERS" ;;
  help|*) echo "usage: $0 {fetch|reflect|serve|all}"; exit 2 ;;
esac
