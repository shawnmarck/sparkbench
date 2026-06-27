#!/usr/bin/env bash
# Full golden workflow for one or more inventory paths (golden + kv sweep + ctx ladder).
set -euo pipefail
ROOT="${SPARK_ROOT:-/opt/spark}"
PY="${ROOT}/venv/bin/python3"
WORKFLOW="${ROOT}/scripts/spark-golden-workflow.py"
LOG="${ROOT}/logs/golden-workflow.log"

if [[ $# -lt 1 ]]; then
  echo "usage: spark-new-model-golden.sh <lab/slug> [lab/slug ...]" >&2
  echo "example: spark-new-model-golden.sh qwen/qwen-agentworld-35b-a3b" >&2
  exit 1
fi

ONLY=$(IFS=,; echo "$*")
echo "Golden workflow --only ${ONLY} (--skip-shelf)"
exec "${PY}" "${WORKFLOW}" --only "${ONLY}" --skip-shelf
