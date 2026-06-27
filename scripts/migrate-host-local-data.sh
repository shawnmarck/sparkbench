#!/usr/bin/env bash
# One-time host hygiene: move legacy runtime YAML out of data/ into gitignored paths.
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
cd "$ROOT"
mkdir -p run

if [[ -f data/inference-benchmark-history.yaml && ! -f run/inference-benchmark-history.yaml ]]; then
  mv data/inference-benchmark-history.yaml run/inference-benchmark-history.yaml
  echo "Moved inference-benchmark-history.yaml → run/"
elif [[ -f data/inference-benchmark-history.yaml ]]; then
  echo "Note: both data/ and run/ benchmark history exist — keeping run/ copy"
fi

for q in hf-download-queue.yaml hf-explore-queue.yaml; do
  if [[ ! -f "data/$q" ]]; then
    printf 'items: []\n' > "data/$q"
    echo "Created empty data/$q"
  fi
done

echo "OK: host-local runtime paths ready (gitignored under data/hf-*, run/)"
