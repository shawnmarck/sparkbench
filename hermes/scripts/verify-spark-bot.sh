#!/usr/bin/env bash
# Health checks for spark-bot on sparky.
set -euo pipefail

HOST="${SPARKY_HOST:-sparky}"
URL="http://${HOST}:9119"
CREDS_FILE="${SPARKY_HERMES_SECURE:-$HOME/secure/sparky-hermes}/dashboard-credentials.txt"
CURL_AUTH=()
if [[ -f "$CREDS_FILE" ]]; then
  # file format: "# Dashboard: username techno, password sparky-hermes-202606"
  pass="$(sed -n 's/^# Dashboard: username techno, password //p' "$CREDS_FILE" | head -1)"
  if [[ -n "$pass" ]]; then
    CURL_AUTH=(-u "techno:${pass}")
  fi
fi

echo "==> Container status"
ssh "$HOST" "docker ps --filter name=spark-bot --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

echo ""
echo "==> Dashboard HTTP"
if curl -sf --max-time 10 "${CURL_AUTH[@]}" "${URL}/" -o /dev/null; then
  echo "OK ${URL}"
else
  echo "FAIL ${URL}" >&2
  ssh "$HOST" "docker logs spark-bot --tail 40" >&2 || true
  exit 1
fi

echo ""
echo "==> Hermes doctor (non-interactive)"
ssh "$HOST" "docker exec spark-bot hermes doctor 2>/dev/null | head -30" || echo "(doctor unavailable or still starting)"

echo ""
echo "Dashboard: ${URL}"