#!/usr/bin/env bash
# Create /models layout on Spark + optional shelf mirror skeleton, docs, sync script.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
STAGING="${SPARK_STAGING}"
SPARK_ROOT="${SPARK_ROOT}"
MODELS="/models"
SHELF_MODELS="${SPARK_SHELF_MOUNT}/models"

echo "==> Sync staging to ${SPARK_ROOT}"
mkdir -p "${SPARK_ROOT}"/{portal,docs,install,services,scripts}
rsync -a "${STAGING}/docs/" "${SPARK_ROOT}/docs/"
rsync -a "${STAGING}/scripts/" "${SPARK_ROOT}/scripts/"
rsync -a "${STAGING}/install/" "${SPARK_ROOT}/install/"
chown -R "${SPARK_USER}:${SPARK_USER}" "${SPARK_ROOT}"

echo "==> Creating Spark model workspace ${MODELS}"
mkdir -p "${MODELS}/_incoming"
mkdir -p "${MODELS}/.keep"
chown -R "${SPARK_USER}:${SPARK_USER}" "${MODELS}"
chmod 755 "${MODELS}"
chmod 755 "${MODELS}/_incoming"

cat > "${MODELS}/README.md" <<'EOF'
# /models — Spark model workspace

Primary download and inference path on this machine. Layout mirrors the NAS shelf when configured.

```
/models/
  _incoming/              partial downloads → promote when complete
  {lab}/{model-version}/
    manifest.yaml
    gguf/                   llama.cpp
    hf/                     HuggingFace / vLLM safetensors layout
    nvfp4/                  GB10-optimized exports
    awq/  gptq/             optional pre-quant trees
```

**Flow:** download here first → smoke test → optionally push to NAS shelf:
```bash
spark shelf push google/gemma-4-26b-a4b
```

Docs: /opt/spark/docs/guides/model-shelf.md
EOF
chown "${SPARK_USER}:${SPARK_USER}" "${MODELS}/README.md"

echo "==> Creating shelf mirror ${SHELF_MODELS} (when NAS is mounted)"
if shelf_mounted; then
  mkdir -p "${SHELF_MODELS}/_incoming"
  chown -R "${SPARK_USER}:${SPARK_USER}" "${SHELF_MODELS}" 2>/dev/null || true
  cat > "${SHELF_MODELS}/README.md" <<'EOF'
# NAS model shelf (mirror of Spark /models)

Backup and long-term storage. Same directory layout as /models on Spark.

Hermes or manual drops for later: use `_incoming/`, then promote into the tree.

Restore to Spark:
```bash
spark shelf pull google/gemma-4-26b-a4b
```
EOF
  chown "${SPARK_USER}:${SPARK_USER}" "${SHELF_MODELS}/README.md" 2>/dev/null || true
  echo "OK: shelf models directory ready"
else
  echo "OK: NAS shelf not mounted — skipped (local /models only; run: spark-install nas)"
fi

echo "==> Shelf CLI via spark shelf push|pull (after spark-install core)"

echo
echo "Done."
echo "  Spark:  ${MODELS}"
echo "  Shelf:  ${SHELF_MODELS} (optional)"
echo "  Docs:   ${SPARK_ROOT}/docs/guides/model-shelf.md"
ls -la "${MODELS}"
