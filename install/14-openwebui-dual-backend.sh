#!/usr/bin/env bash
# Open WebUI with vLLM + llama.cpp dual OpenAI connections.
set -euo pipefail

STAGING="/home/techno/spark"
SPARK_ROOT="/opt/spark"
COMPOSE_SRC="${STAGING}/services/open-webui/compose.yaml"
COMPOSE_DST="${SPARK_ROOT}/services/open-webui/compose.yaml"

echo "==> Install open-webui compose"
mkdir -p "${SPARK_ROOT}/services/open-webui"
install -m 644 "${COMPOSE_SRC}" "${COMPOSE_DST}"
chown techno:techno "${COMPOSE_DST}"

echo "==> Recreate Open WebUI (preserves chat volume)"
docker stop spark-open-webui 2>/dev/null || true
docker rm spark-open-webui 2>/dev/null || true
docker compose -f "${COMPOSE_DST}" up -d open-webui

echo "==> Wait for health"
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:3000/health >/dev/null 2>&1 || curl -sf http://127.0.0.1:3000/ >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo
echo "Done. Open WebUI: http://sparky:3000"
echo "  vLLM API:  http://host.docker.internal:8000/v1  (spark engine eugr up)"
echo "  llama API: http://host.docker.internal:8081/v1  (spark engine llama up)"
echo "Pick model qwen3.6-35b-a3b-q4 when llama.cpp is running."
