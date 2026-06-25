#!/usr/bin/env bash
# Rsync spark-bot agent state to NAS. Run from techno or sparky.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/paths.sh
source "${ROOT}/scripts/lib/paths.sh"
SOURCE="${SPARKY_HERMES_DATA:-${REMOTE_DATA}}"
# Override destination, e.g. NAS_BACKUP_DEST=pollynas:/backups/sparky/hermes/spark-bot/
DEST="${NAS_BACKUP_DEST:-}"

if [[ -z "$DEST" ]]; then
  echo "Set NAS_BACKUP_DEST, e.g.:" >&2
  echo "  NAS_BACKUP_DEST=pollynas:/volume1/backups/sparky/hermes/spark-bot/ $0" >&2
  exit 1
fi

if [[ "$(hostname -s 2>/dev/null || hostname)" == "$HOST" ]] || [[ "$HOST" == "localhost" ]]; then
  SRC_PATH="$SOURCE/"
else
  SRC_PATH="${HOST}:${SOURCE}/"
fi

rsync -av --delete \
  --exclude='logs/*.log' \
  "$SRC_PATH" "$DEST"

echo "Backup complete: $SRC_PATH -> $DEST"