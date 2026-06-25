#!/usr/bin/env bash
# One-time: move Hermes runtime from /opt/spark/hermes to /opt/hermes (or SPARKY_HERMES_ROOT).
# Run from techno after updating this repo; then ./deploy-spark-bot.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/paths.sh
source "${ROOT}/scripts/lib/paths.sh"

echo "==> Migrate Hermes: ${LEGACY_HERMES_ROOT} -> ${SPARKY_HERMES_ROOT} on ${HOST}"

ssh "$HOST" "test -d '${LEGACY_HERMES_ROOT}'" || {
  echo "No legacy dir at ${LEGACY_HERMES_ROOT} — nothing to migrate." >&2
  exit 0
}

ssh "$HOST" "test ! -e '${SPARKY_HERMES_ROOT}' || test -d '${SPARKY_HERMES_ROOT}'" || {
  echo "Refusing: ${SPARKY_HERMES_ROOT} exists and is not a directory." >&2
  exit 1
}

echo "==> Ensure ${SPARKY_HERMES_ROOT} exists (techno-owned)"
ssh "$HOST" "mkdir -p '${SPARKY_HERMES_ROOT}' && chown techno:techno '${SPARKY_HERMES_ROOT}' 2>/dev/null || true"

echo "==> Stop spark-bot if running"
ssh "$HOST" "cd '${LEGACY_HERMES_ROOT}' 2>/dev/null && docker compose stop spark-bot 2>/dev/null || true"

echo "==> Rsync legacy tree -> new root"
ssh "$HOST" "rsync -a '${LEGACY_HERMES_ROOT}/' '${SPARKY_HERMES_ROOT}/'"

echo "==> Deploy with new paths (compose + config)"
"${ROOT}/scripts/deploy-spark-bot.sh"

echo ""
echo "==> Migration complete."
echo "    Verify: ${ROOT}/scripts/verify-spark-bot.sh"
echo "    After verify, optionally remove legacy data:"
echo "      ssh ${HOST} 'rm -rf ${LEGACY_HERMES_ROOT}'"