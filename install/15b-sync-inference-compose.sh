#!/usr/bin/env bash
set -euo pipefail
cp /home/techno/spark/services/qwen36-nvfp4/compose.yaml /opt/spark/services/qwen36-nvfp4/compose.yaml
cp /home/techno/spark/portal/index.html /opt/spark/portal/
echo "Synced compose + portal"
cp /home/techno/spark/docs/INFERENCE-SMOKE.md /opt/spark/docs/
