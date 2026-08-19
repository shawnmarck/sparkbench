#!/bin/bash
# Overlay vLLM PR 52816 (DFlash2) onto the installed package.
# Idempotent. Safe for DFlash v1 / DSpark / MTP — new architecture only.
set -euo pipefail

PREFIX="[eugr-dflash2]"
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="$MOD_DIR/prod.patch"

if ! command -v python3 >/dev/null 2>&1; then
    echo "$PREFIX python3 is required." >&2
    exit 1
fi

if [ -z "${VLLM_PACKAGE_ROOT:-}" ]; then
    VLLM_PACKAGE_ROOT=$(python3 - <<'PY'
import importlib.util
spec = importlib.util.find_spec("vllm")
if spec is None or not spec.submodule_search_locations:
    raise SystemExit("vLLM package is not installed")
print(next(iter(spec.submodule_search_locations)))
PY
    )
fi

REGISTRY="$VLLM_PACKAGE_ROOT/model_executor/models/registry.py"
if [ ! -f "$REGISTRY" ]; then
    echo "$PREFIX vLLM registry not found: $REGISTRY" >&2
    exit 1
fi

has_dflash2() {
    grep -q 'DFlash2DraftModel' "$REGISTRY"
}

if has_dflash2 && [ -f "$VLLM_PACKAGE_ROOT/model_executor/models/qwen3_dflash2.py" ]; then
    echo "$PREFIX DFlash2 already present; skipping."
    python3 -m py_compile \
        "$VLLM_PACKAGE_ROOT/model_executor/models/qwen3_dflash2.py" \
        "$VLLM_PACKAGE_ROOT/v1/worker/gpu/spec_decode/dflash2/speculator.py"
    exit 0
fi

SITE_PACKAGES="$(dirname "$VLLM_PACKAGE_ROOT")"
if [ ! -f "$PATCH_FILE" ]; then
    echo "$PREFIX missing $PATCH_FILE" >&2
    exit 1
fi

apply_ok=0
if command -v git >/dev/null 2>&1; then
    if git -C "$SITE_PACKAGES" apply --check "$PATCH_FILE" 2>/dev/null; then
        git -C "$SITE_PACKAGES" apply "$PATCH_FILE"
        apply_ok=1
    fi
fi
if [ "$apply_ok" -eq 0 ] && command -v patch >/dev/null 2>&1; then
    if patch -d "$SITE_PACKAGES" -p1 --dry-run < "$PATCH_FILE" >/dev/null 2>&1; then
        patch -d "$SITE_PACKAGES" -p1 < "$PATCH_FILE"
        apply_ok=1
    fi
fi
if [ "$apply_ok" -eq 0 ]; then
    echo "$PREFIX could not apply prod.patch to $SITE_PACKAGES" >&2
    echo "$PREFIX Need a vLLM build close to f9f066d19 / 0.27.2rc1 with DFlash v1." >&2
    exit 1
fi

install -m 644 "$MOD_DIR/files/qwen3_dflash2.py" \
    "$VLLM_PACKAGE_ROOT/model_executor/models/qwen3_dflash2.py"
install -d "$VLLM_PACKAGE_ROOT/v1/worker/gpu/spec_decode/dflash2"
install -m 644 "$MOD_DIR/files/dflash2/__init__.py" \
    "$VLLM_PACKAGE_ROOT/v1/worker/gpu/spec_decode/dflash2/__init__.py"
install -m 644 "$MOD_DIR/files/dflash2/speculator.py" \
    "$VLLM_PACKAGE_ROOT/v1/worker/gpu/spec_decode/dflash2/speculator.py"

if ! has_dflash2; then
    echo "$PREFIX registry postcondition failed — DFlash2DraftModel missing." >&2
    exit 1
fi

python3 -m py_compile \
    "$VLLM_PACKAGE_ROOT/config/vllm.py" \
    "$VLLM_PACKAGE_ROOT/model_executor/models/qwen3_dflash.py" \
    "$VLLM_PACKAGE_ROOT/model_executor/models/qwen3_dflash2.py" \
    "$VLLM_PACKAGE_ROOT/model_executor/models/registry.py" \
    "$VLLM_PACKAGE_ROOT/v1/worker/gpu/spec_decode/__init__.py" \
    "$VLLM_PACKAGE_ROOT/v1/worker/gpu/spec_decode/dflash2/speculator.py"

echo "$PREFIX Applied vLLM PR 52816 overlay (DFlash2DraftModel + V2 speculator)."
