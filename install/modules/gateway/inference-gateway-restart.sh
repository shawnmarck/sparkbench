#!/usr/bin/env bash
# Restart inference gateway only (passwordless via install/*.sh sudoers rule).
# Does not stop the GPU engine.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

systemctl restart spark-inference-gateway.service
sleep 1
curl -fsS "http://127.0.0.1:9000/v1/models" >/dev/null
echo "OK: spark-inference-gateway restarted"
