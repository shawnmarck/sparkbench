#!/usr/bin/env bash
# Create /models layout on Spark + shelf mirror skeleton, docs, sync script.
set -euo pipefail

STAGING="/home/techno/spark"
SPARK_ROOT="/opt/spark"
MODELS="/models"
SHELF_MODELS="/mnt/model-shelf/models"
TECHNO="techno"

echo "==> Sync staging to ${SPARK_ROOT}"
mkdir -p "${SPARK_ROOT}"/{portal,docs,install,services,scripts}
rsync -a "${STAGING}/docs/" "${SPARK_ROOT}/docs/"
rsync -a "${STAGING}/scripts/" "${SPARK_ROOT}/scripts/"
rsync -a "${STAGING}/install/" "${SPARK_ROOT}/install/"
chown -R "${TECHNO}:${TECHNO}" "${SPARK_ROOT}"

echo "==> Creating Spark model workspace ${MODELS}"
mkdir -p "${MODELS}/_incoming"
mkdir -p "${MODELS}/.keep"
chown -R "${TECHNO}:${TECHNO}" "${MODELS}"
chmod 755 "${MODELS}"
chmod 755 "${MODELS}/_incoming"

cat > "${MODELS}/README.md" <<'EOF'
# /models — Spark model workspace

Primary download and inference path on this machine. Layout mirrors the NAS shelf.

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

**Flow:** download here first → smoke test → push to shelf:
```bash
spark-shelf-push google/gemma-4-26b-a4b
```

Docs: /opt/spark/docs/MODEL-SHELF.md
EOF
chown "${TECHNO}:${TECHNO}" "${MODELS}/README.md"

echo "==> Creating shelf mirror ${SHELF_MODELS}"
if mountpoint -q /mnt/model-shelf; then
  mkdir -p "${SHELF_MODELS}/_incoming"
  chown -R "${TECHNO}:${TECHNO}" "${SHELF_MODELS}" 2>/dev/null || true
  cat > "${SHELF_MODELS}/README.md" <<'EOF'
# NAS model shelf (mirror of Spark /models)

Backup and long-term storage. Same directory layout as /models on Spark.

Hermes or manual drops for later: use `_incoming/`, then promote into the tree.

Restore to Spark:
```bash
spark-shelf-pull google/gemma-4-26b-a4b
```
EOF
  chown "${TECHNO}:${TECHNO}" "${SHELF_MODELS}/README.md" 2>/dev/null || true
  echo "OK: shelf models directory ready"
else
  echo "WARN: /mnt/model-shelf not mounted; shelf dirs skipped"
fi

echo "==> Installing spark-shelf-push / spark-shelf-pull"
install -m 755 "${SPARK_ROOT}/scripts/spark-shelf-push" /usr/local/bin/spark-shelf-push
install -m 755 "${SPARK_ROOT}/scripts/spark-shelf-pull" /usr/local/bin/spark-shelf-pull

echo
echo "Done."
echo "  Spark:  ${MODELS}"
echo "  Shelf:  ${SHELF_MODELS}"
echo "  Docs:   ${SPARK_ROOT}/docs/MODEL-SHELF.md"
ls -la "${MODELS}"
