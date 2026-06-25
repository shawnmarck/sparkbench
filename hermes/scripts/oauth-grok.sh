#!/usr/bin/env bash
# Grok (xAI) OAuth for spark-bot — requires an interactive terminal.
#
# Option A (one command):
#   ssh -t sparky 'docker exec -it spark-bot hermes auth add xai-oauth --manual-paste'
#
# Option B (two steps):
#   ssh -t sparky
#   docker exec -it spark-bot hermes auth add xai-oauth --manual-paste
#
# Flow:
# 1. Hermes prints an accounts.x.ai URL — open it in your local browser
# 2. Sign in with SuperGrok / X Premium account
# 3. Browser redirects to 127.0.0.1:56121 (will fail — expected)
# 4. Copy the full callback URL from the address bar (or the code shown)
# 5. Paste into the terminal when prompted
#
# Tokens persist at /opt/hermes/data/spark-bot/data/auth.json

set -euo pipefail

HOST="${SPARKY_HOST:-sparky}"

if [[ ! -t 0 ]] || [[ ! -t 1 ]]; then
  echo "This script needs a TTY. Run:" >&2
  echo "  ssh -t ${HOST} 'docker exec -it spark-bot hermes auth add xai-oauth --manual-paste'" >&2
  exit 1
fi

exec ssh -t "$HOST" "docker exec -it spark-bot hermes auth add xai-oauth --manual-paste"