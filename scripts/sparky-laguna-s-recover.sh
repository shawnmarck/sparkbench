#!/usr/bin/env bash
# Recover Sparky after Laguna flashinfer_cutlass OOM thrash.
# Run from techno once SSH works: bash scripts/sparky-laguna-s-recover.sh
set -euo pipefail
HOST="${SPARKY_HOST:-sparky}"
ssh -o BatchMode=yes -o ConnectTimeout=30 "$HOST" bash -s <<'REMOTE'
set -euo pipefail
echo "==> host $(hostname) $(uptime)"
free -h | head -2

echo "==> stop inference / kill thrashing vllm"
spark inference down || true
spark engine eugr down || true
docker kill vllm_node 2>/dev/null || true
docker rm -f vllm_node 2>/dev/null || true
sleep 2
free -h | head -2

echo "==> eugr pin check"
/opt/spark/venv/bin/python /opt/spark/scripts/spark-eugr-check.py check || true

echo "==> ready for recipe deploy + golden rebench from techno"
REMOTE

scp \
  /home/techno/projects/sparkbench/services/eugr-poolside-laguna-s-2-1-dflash-eugr.yaml \
  /home/techno/projects/sparkbench/recipes/poolside-laguna-s-2-1-dflash-eugr.yaml \
  "$HOST:/tmp/"

ssh -o BatchMode=yes "$HOST" bash -s <<'REMOTE'
set -euo pipefail
cp /tmp/eugr-poolside-laguna-s-2-1-dflash-eugr.yaml /opt/spark/services/
cp /tmp/poolside-laguna-s-2-1-dflash-eugr.yaml /opt/spark/recipes/
# keep lifecycle works if already set
echo "==> smoke load (marlin, max_num_seqs=4)"
spark inference up poolside-laguna-s-2-1-dflash-eugr --preset smoke
REMOTE

echo "Smoke started — monitor with: ssh $HOST 'spark inference status; docker logs vllm_node 2>&1 | tail'"
echo "When ready: ssh $HOST 'nohup /opt/spark/venv/bin/python3 /opt/spark/scripts/golden-inventory-audit.py --only poolside/laguna-s-2.1 --skip-shelf >> /opt/spark/logs/golden-audit-laguna-s.log 2>&1 &'"
