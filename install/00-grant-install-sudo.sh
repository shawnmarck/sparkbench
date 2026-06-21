#!/usr/bin/env bash
# One-time: enter sudo password, then install runs without prompting again.
set -euo pipefail

SUDOERS="/etc/sudoers.d/spark-install"
RULE='techno ALL=(ALL) NOPASSWD: /home/techno/spark/install/*.sh, /opt/spark/install/*.sh'

echo "This will:"
echo "  1. Allow passwordless sudo ONLY for ~/spark/install/*.sh scripts"
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

sudo bash ~/spark/install/01-netdata-portal.sh
