#!/usr/bin/env bash
# Debounced, locked inventory rebuild (safe for timer + inotify)
set -euo pipefail
RUN_DIR="/opt/spark/run"
mkdir -p "$RUN_DIR"
LOCK="${RUN_DIR}/inventory-refresh.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  exit 0
fi
/opt/spark/venv/bin/python /opt/spark/scripts/spark-inventory-build.py
