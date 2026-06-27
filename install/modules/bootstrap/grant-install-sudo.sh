#!/usr/bin/env bash
# One-time: enter sudo password once, then install runs without prompting again.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

SUDOERS="/etc/sudoers.d/spark-install"
RULE="${SPARK_USER} ALL=(ALL) NOPASSWD: ${SPARK_STAGING}/install/spark-install, ${SPARK_ROOT}/install/spark-install, ${SPARK_STAGING}/install/modules/*/*.sh, ${SPARK_ROOT}/install/modules/*/*.sh"

echo "This will:"
echo "  1. Allow passwordless sudo for install/spark-install and install/modules/*/*.sh (user: ${SPARK_USER})"
echo "  2. Run the Netdata + portal base module"
echo

if [ ! -f "$SUDOERS" ] || ! grep -qF "spark/install" "$SUDOERS" 2>/dev/null; then
  echo "$RULE" | sudo tee "$SUDOERS" >/dev/null
  sudo chmod 440 "$SUDOERS"
  sudo visudo -cf "$SUDOERS"
  echo "OK: sudoers rule added ($SUDOERS)"
else
  echo "OK: sudoers rule already present"
fi

sudo bash "${SPARK_ROOT}/install/modules/core/portal-base.sh"
