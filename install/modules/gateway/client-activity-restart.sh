#!/usr/bin/env bash
# Restart client activity API (passwordless via install/*.sh sudoers rule).
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

systemctl restart spark-client-activity.service
sleep 1
curl -fsS "http://127.0.0.1:8769/api/activity?window=1h" >/dev/null
echo "OK: spark-client-activity restarted"
