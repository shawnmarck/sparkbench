#!/usr/bin/env bash
# Mark host-local files as skip-worktree so git pull does not fight per-box toggles.
# Shared cookbook (recipes + data/*.yaml perf) is NOT protected — it travels in git.
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
cd "$ROOT"

HOST_LOCAL_PATHS=(
  data/inference-profiles.yaml
  data/inference-benchmarks.yaml
)

protected=0
for path in "${HOST_LOCAL_PATHS[@]}"; do
  if git ls-files --error-unmatch "$path" &>/dev/null; then
    git update-index --skip-worktree "$path"
    protected=$((protected + 1))
  fi
done

echo "==> skip-worktree on $protected host-local file(s)"
git ls-files -v | grep '^[S]' | awk '{print "  ", $2}' || true
echo ""
echo "Shared cookbook (recipes/, data/golden-recipes.yaml, data/model-catalog.yaml,"
echo "data/model-verification.yaml) is pulled from git — not skip-worktree."
