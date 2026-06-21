#!/usr/bin/env bash
set -euo pipefail
OPS="/ops/vllm-studio"
REPO="${OPS}/repo"
FRONTEND_PORT=3080
CTRL_PORT=8080
BUN="/home/techno/.bun/bin/bun"
TECHNO="techno"

echo "==> Node 22 (undici 8 / Next.js 16 requirement)"
if ! node --version 2>/dev/null | grep -qE '^v22'; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -qq nodejs
fi
node --version

echo "==> Frontend build"
sudo -u "$TECHNO" bash -lc "
  cd '${REPO}/frontend'
  npm run build
"

echo "==> Enable services"
systemctl daemon-reload
systemctl enable spark-vllm-studio-controller.service spark-vllm-studio-frontend.service 2>/dev/null || true
systemctl restart spark-vllm-studio-controller.service
sleep 5
systemctl restart spark-vllm-studio-frontend.service

sleep 3
systemctl is-active spark-vllm-studio-controller.service spark-vllm-studio-frontend.service
curl -sf "http://127.0.0.1:${CTRL_PORT}/health" | head -c 200 || echo "controller health pending"
curl -sf -o /dev/null -w '%{http_code}' "http://127.0.0.1:${FRONTEND_PORT}/" || echo "frontend pending"

echo
echo "vLLM Studio: http://sparky:${FRONTEND_PORT}"
