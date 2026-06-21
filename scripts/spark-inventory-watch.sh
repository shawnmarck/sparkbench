#!/usr/bin/env bash
# Debounce /models filesystem events → inventory rebuild
set -euo pipefail
MODELS="/models"
DEBOUNCE_SEC=45
RUN_DIR="/opt/spark/run"
mkdir -p "$RUN_DIR"
STAMP="${RUN_DIR}/inventory-watch.stamp"

run_refresh() {
  local now last
  now=$(date +%s)
  last=$(cat "$STAMP" 2>/dev/null || echo 0)
  if (( now - last < DEBOUNCE_SEC )); then
    return 0
  fi
  echo "$now" > "$STAMP"
  /opt/spark/scripts/spark-inventory-refresh.sh || true
}

[[ -d "$MODELS" ]] || exit 1
run_refresh

inotifywait -m -r -e close_write,create,delete,move --format '%w%f' "$MODELS" 2>/dev/null |
while read -r _path; do
  run_refresh
done
