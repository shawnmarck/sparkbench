#!/usr/bin/env bash
# One-time: enter sudo password once, then the Grok agent can sudo without prompting.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

SUDOERS="/etc/sudoers.d/spark-agent"
RULE="${SPARK_USER} ALL=(ALL) NOPASSWD: ALL"

echo "Spark agent sudo grant"
echo "======================"
echo
echo "This adds passwordless sudo for user '${SPARK_USER}' on this host."
echo "Scope: full admin (apt, systemctl, mounts, /etc, etc.)"
echo "File: $SUDOERS"
echo
echo "Existing /etc/sudoers.d/spark-install (install scripts only) is left unchanged."
echo "Revoke anytime: sudo rm $SUDOERS && sudo visudo -c"
echo

if [ -f "$SUDOERS" ] && grep -qF "NOPASSWD: ALL" "$SUDOERS" 2>/dev/null; then
  echo "OK: agent sudo rule already present"
else
  echo "$RULE" | tee "$SUDOERS" >/dev/null
  chmod 440 "$SUDOERS"
  visudo -cf "$SUDOERS"
  echo "OK: agent sudo rule added"
fi

if sudo -u "${SPARK_USER}" sudo -n true 2>/dev/null; then
  echo "Verified: ${SPARK_USER} can sudo without a password"
else
  echo "Note: verification skipped (run as root during install is normal)"
fi
