#!/usr/bin/env bash
# Apply idempotent patch scripts to spark-inference.py and related tooling on sparky.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PATCHES=(
  patch-eugr-state-writable.py
  patch-inference-bench-v2.py
  patch-eugr-language-model-only.py
  patch-eugr-qwen-tool-choice.py
)

for p in "${PATCHES[@]}"; do
  path="$ROOT/scripts/$p"
  if [[ -f "$path" ]]; then
    echo "==> $p"
    python3 "$path" || true
  fi
done

# Repair known bad string states if a patch half-applied
for fix in fix-spark-inference-lmo-string.py fix-spark-inference-qwen-agent-lines.py; do
  if [[ -f "$ROOT/scripts/$fix" ]]; then
    python3 "$ROOT/scripts/$fix" 2>/dev/null || true
  fi
done

python3 -m py_compile "$ROOT/scripts/spark-inference.py"
echo "==> spark-inference.py OK"
