#!/usr/bin/env bash
# Restart inference gateway only (passwordless via install/*.sh sudoers rule).
# Does not stop the GPU engine.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

systemctl restart spark-inference-gateway.service
sleep 1
# 200 = models listed; 503 = gateway up but engine not ready. Both are healthy.
code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:9000/v1/models" || true)"
if [[ "${code}" != "200" && "${code}" != "503" ]]; then
  echo "FAIL: gateway /v1/models returned ${code:-none}" >&2
  exit 1
fi
echo "OK: spark-inference-gateway restarted (models ${code})"
