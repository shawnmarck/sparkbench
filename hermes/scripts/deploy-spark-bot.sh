#!/usr/bin/env bash
# Deploy spark-bot Hermes agent to sparky.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$ROOT/scripts"
# shellcheck source=lib/paths.sh
source "${SCRIPTS}/lib/paths.sh"

echo "==> Deploy spark-bot -> ${HOST}"

"${SCRIPTS}/render-secrets.sh"

ssh "$HOST" "mkdir -p ${REMOTE_DATA}/bin ${REMOTE_DATA}/skills ${REMOTE_DATA}/logs ${REMOTE_WORKSPACE}"

scp "${ROOT}/compose.yml" "${HOST}:${SPARKY_HERMES_ROOT}/docker-compose.yml"
scp "${ROOT}/spark-bot/SOUL.md" "${HOST}:${REMOTE_DATA}/SOUL.md"
scp "${ROOT}/spark-bot/AGENTS.md" "${HOST}:${REMOTE_DATA}/AGENTS.md"
scp "${SCRIPTS}/apply-config.py" "${HOST}:${REMOTE_DATA}/bin/apply-config.py"
ssh "$HOST" "chmod 755 ${REMOTE_DATA}/bin/apply-config.py"

# Merge overlay into config.yaml on sparky (local python3)
scp "${ROOT}/spark-bot/config-overlay.yaml" "${HOST}:/tmp/spark-bot-overlay.yaml"
scp "${ROOT}/spark-bot/config-base.yaml" "${HOST}:/tmp/spark-bot-base.yaml"
ssh "$HOST" "python3 ${REMOTE_DATA}/bin/apply-config.py \
  --config ${REMOTE_DATA}/config.yaml \
  --overlay /tmp/spark-bot-overlay.yaml \
  --base /tmp/spark-bot-base.yaml"
ssh "$HOST" "rm -f /tmp/spark-bot-overlay.yaml /tmp/spark-bot-base.yaml"

echo "==> Pull image and start container"
ssh "$HOST" "cd ${SPARKY_HERMES_ROOT} && docker compose pull spark-bot && docker compose up -d --force-recreate spark-bot"

echo "==> Deploy complete. Verify:"
echo "    ${SCRIPTS}/verify-spark-bot.sh"
echo "    http://${HOST}:9119"
echo ""
echo "Grok OAuth (one-time, needs TTY):"
echo "    ssh -t ${HOST} 'docker exec -it spark-bot hermes auth add xai-oauth --manual-paste'"
echo "    # or: ${SCRIPTS}/oauth-grok.sh"