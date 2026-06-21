#!/usr/bin/env bash
# DFlash + PrismaQuant extras (parallel-safe; separate paths from main batch)
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/qwen36-27b-extras-${TS}.log"

exec > >(tee -a "$LOG") 2>&1

echo "==> Qwen3.6 extras download started $(date -Is)"
echo "Log: $LOG"

download_repo() {
  local repo="$1" dest="$2"
  echo
  echo "==> REPO $repo -> $dest"
  mkdir -p "$dest"
  "$HF" download "$repo" --local-dir "$dest"
}

download_repo z-lab/Qwen3.6-27B-DFlash /models/z-lab/qwen3.6-27b/dflash
download_repo rdtand/Qwen3.6-27B-PrismaQuant-5.5bit-vllm /models/rdtand/qwen3.6-27b/prismaquant
download_repo z-lab/Qwen3.6-35B-A3B-DFlash /models/z-lab/qwen3.6-35b-a3b/dflash

echo
echo "==> Extras finished $(date -Is)"
du -sh /models/z-lab/qwen3.6-27b/* /models/rdtand/qwen3.6-27b/* /models/z-lab/qwen3.6-35b-a3b/* 2>/dev/null | sort -hr || true