#!/usr/bin/env bash
# One-time: SSH key for spark-bot gateway -> sparky host (techno@/opt/spark).
# Run from techno after deploy. Does NOT use the agent — avoids keys in chat logs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/paths.sh
source "${ROOT}/scripts/lib/paths.sh"

KEY_NAME="spark-bot-terminal"
REMOTE_KEY_DIR="${REMOTE_DATA}/home/.ssh"
REMOTE_KEY="${REMOTE_KEY_DIR}/${KEY_NAME}"
AUTH_MARKER="spark-bot-terminal@hermes"
SSH_HOST_ALIAS="${SPARKY_SSH_HOST:-host.docker.internal}"

echo "==> SSH terminal setup for spark-bot on ${HOST}"

ssh "$HOST" "mkdir -p '${REMOTE_KEY_DIR}' && chmod 700 '${REMOTE_KEY_DIR}'"

if ssh "$HOST" "test -f '${REMOTE_KEY}'"; then
  echo "    Key already exists: ${REMOTE_KEY}"
else
  echo "==> Generate ed25519 key on sparky (no passphrase)"
  ssh "$HOST" "ssh-keygen -t ed25519 -f '${REMOTE_KEY}' -N '' -C '${AUTH_MARKER}'"
fi

ssh "$HOST" "chmod 600 '${REMOTE_KEY}' '${REMOTE_KEY}.pub'"

echo "==> Write SSH config inside spark-bot profile (Hermes + manual ssh)"
ssh "$HOST" "cat > '${REMOTE_KEY_DIR}/config' <<'EOF'
Host host.docker.internal sparky
  HostName host.docker.internal
  User techno
  IdentityFile /opt/data/home/.ssh/spark-bot-terminal
  StrictHostKeyChecking accept-new
  BatchMode yes
EOF
chmod 600 '${REMOTE_KEY_DIR}/config'"

PUBKEY="$(ssh "$HOST" "cat '${REMOTE_KEY}.pub'")"

echo "==> Install public key in techno@sparky authorized_keys"
ssh "$HOST" "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
if ssh "$HOST" "grep -qF '${AUTH_MARKER}' ~/.ssh/authorized_keys"; then
  echo "    authorized_keys already has ${AUTH_MARKER}"
else
  ssh "$HOST" "echo '${PUBKEY}' >> ~/.ssh/authorized_keys"
  echo "    Appended pubkey to ~/.ssh/authorized_keys"
fi

echo "==> Deploy compose (host.docker.internal) + SSH terminal config"
"${ROOT}/scripts/deploy-spark-bot.sh"

echo "==> Test SSH from spark-bot container"
if ssh "$HOST" "docker exec spark-bot ssh -i /opt/data/home/.ssh/${KEY_NAME} \
  -o StrictHostKeyChecking=accept-new \
  -o BatchMode=yes \
  techno@${SSH_HOST_ALIAS} 'echo ok-ssh && pwd && which spark && spark inference status 2>/dev/null | head -3'"; then
  echo ""
  echo "==> SSH terminal ready."
else
  echo "" >&2
  echo "SSH test failed. Try:" >&2
  echo "  ssh ${HOST} \"docker exec spark-bot ssh -v -i /opt/data/home/.ssh/${KEY_NAME} techno@${SSH_HOST_ALIAS}\"" >&2
  echo "  Or set SPARKY_SSH_HOST=172.17.0.1 and re-run this script." >&2
  exit 1
fi