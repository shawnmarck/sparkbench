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

# Shared cookbook must never be skip-worktree (legacy mistake on some hosts).
SHARED_COOKBOOK_PATHS=(
  data/model-catalog.yaml
  data/model-verification.yaml
  data/golden-recipes.yaml
)

cleared=0
for path in "${SHARED_COOKBOOK_PATHS[@]}"; do
  if git ls-files -v "$path" 2>/dev/null | grep -q '^S'; then
    git update-index --no-skip-worktree "$path"
    cleared=$((cleared + 1))
  fi
done
if [[ "$cleared" -gt 0 ]]; then
  echo "==> cleared skip-worktree on $cleared shared cookbook file(s)"
fi

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
echo ""
echo "Host-local runtime (gitignored): run/, logs/, portal/models.json,"
echo "data/hf-*-queue.yaml"
