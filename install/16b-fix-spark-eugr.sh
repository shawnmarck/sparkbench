#!/usr/bin/env bash
set -euo pipefail
cp /home/techno/spark/scripts/spark-eugr /opt/spark/scripts/spark-eugr
chmod +x /opt/spark/scripts/spark-eugr
install -m 755 /opt/spark/scripts/spark-eugr /usr/local/bin/spark-eugr
sudo -u techno spark-eugr up
