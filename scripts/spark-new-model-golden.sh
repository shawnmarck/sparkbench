#!/usr/bin/env bash
# Run golden audit + bench v2 for one or more inventory paths.
set -euo pipefail
ROOT="${SPARK_ROOT:-/opt/spark}"
PY="${ROOT}/venv/bin/python3"
AUDIT="${ROOT}/scripts/golden-inventory-audit.py"
LOG="${ROOT}/logs/golden-audit.log"

if [[ $# -lt 1 ]]; then
  echo "usage: spark-new-model-golden.sh <lab/slug> [lab/slug ...]" >&2
  echo "example: spark-new-model-golden.sh qwen/qwen-agentworld-35b-a3b" >&2
  exit 1
fi

ONLY=$(IFS=,; echo "$*")
echo "Golden audit --only ${ONLY} (--skip-shelf)"
exec "${PY}" "${AUDIT}" --only "${ONLY}" --skip-shelf
