#!/usr/bin/env bash
# Mark sparky runtime files as skip-worktree so git pull never overwrites live audit/bench state.
# Run once on sparky after clone, and again after deploy (deploy calls this automatically).
#
# Undo: git update-index --no-skip-worktree <path>
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
cd "$ROOT"

RUNTIME_PATHS=(
  data/model-verification.yaml
  data/inference-benchmarks.yaml
  data/inference-profiles.yaml
  data/model-catalog.yaml
)

protected=0
for path in "${RUNTIME_PATHS[@]}"; do
  if git ls-files --error-unmatch "$path" &>/dev/null; then
    git update-index --skip-worktree "$path"
    protected=$((protected + 1))
  fi
done

echo "==> skip-worktree on $protected runtime data file(s)"
git ls-files -v | grep '^[S]' | awk '{print "  ", $2}' || true
