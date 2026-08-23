#!/usr/bin/env bash
# Reinstall /usr/local/bin/spark from the tree. No nginx / core rewrite.
set -euo pipefail
install -m 755 /opt/spark/scripts/spark /usr/local/bin/spark
echo "OK: /usr/local/bin/spark refreshed"
