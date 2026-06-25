#!/usr/bin/env bash
# Copy secrets from ~/secure/sparky-hermes/ to sparky agent data dir.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/paths.sh
source "${ROOT}/scripts/lib/paths.sh"
SECURE="${SPARKY_HERMES_SECURE:-$HOME/secure/sparky-hermes}"
SRC="${SECURE}/spark-bot.env"

if [[ ! -f "$SRC" ]]; then
  echo "Missing $SRC" >&2
  echo "Create from hermes/runbooks/deployment.md template." >&2
  exit 1
fi

ssh "$HOST" "mkdir -p ${REMOTE_DATA}"
scp "$SRC" "${HOST}:${REMOTE_DATA}/.env"
ssh "$HOST" "chmod 600 ${REMOTE_DATA}/.env"
echo "Rendered ${SRC} -> ${HOST}:${REMOTE_DATA}/.env"