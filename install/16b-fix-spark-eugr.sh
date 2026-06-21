#!/usr/bin/env bash
set -euo pipefail
cp /home/techno/spark/scripts/spark-eugr /opt/spark/scripts/spark-eugr
chmod +x /opt/spark/scripts/spark-eugr
# CLI: install/20-spark-cli.sh → spark engine eugr
sudo -u techno /opt/spark/scripts/spark-eugr up
