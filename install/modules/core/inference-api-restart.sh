#!/usr/bin/env bash
# Restart inference API (passwordless via install/*.sh sudoers rule).
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

systemctl restart spark-inference-api.service
sleep 1
curl -fsS "http://127.0.0.1:8767/api/inference/status" >/dev/null
echo "OK: spark-inference-api restarted"