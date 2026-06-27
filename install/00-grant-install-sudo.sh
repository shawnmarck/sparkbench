#!/usr/bin/env bash
# One-time: enter sudo password once, then install runs without prompting again.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

SUDOERS="/etc/sudoers.d/spark-install"
RULE="${SPARK_USER} ALL=(ALL) NOPASSWD: ${SPARK_STAGING}/install/*.sh, ${SPARK_ROOT}/install/*.sh, ${SPARK_STAGING}/install/spark-install, ${SPARK_ROOT}/install/spark-install"

echo "This will:"
echo "  1. Allow passwordless sudo ONLY for install/*.sh scripts (user: ${SPARK_USER})"
echo "  2. Run the Netdata + portal install"
echo

if [ ! -f "$SUDOERS" ] || ! grep -qF "spark/install" "$SUDOERS" 2>/dev/null; then
  echo "$RULE" | sudo tee "$SUDOERS" >/dev/null
  sudo chmod 440 "$SUDOERS"
  sudo visudo -cf "$SUDOERS"
  echo "OK: sudoers rule added ($SUDOERS)"
else
  echo "OK: sudoers rule already present"
fi

sudo bash "${SPARK_ROOT}/install/01-netdata-portal.sh"
