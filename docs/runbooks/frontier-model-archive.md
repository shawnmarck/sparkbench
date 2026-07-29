# Frontier model archive (NAS-only)

Cold-archive high-value open weights straight to the QNAP model shelf via Sparky’s mount. **Do not** land these on Sparky `/models` unless you intend to serve them.

## When to use

- Ban / takedown risk for a frontier open-weight model
- Weights too large for a single GB10, but worth keeping on the shelf
- Repeatable path for the next release (e.g. Kimi K3 open weights)

## Paths

| Role | Path |
|------|------|
| NAS shelf (canonical) | `/mnt/model-shelf/models` |
| Partial / staging | `/mnt/model-shelf/models/_incoming` |
| Sparky local (avoid for archive) | `/models` |

Sparky mounts `//192.168.0.99/models` at `/mnt/model-shelf`. This workstation usually does **not** have that mount — run downloads over `ssh sparky`.

## Choose a variant

Prefer the smallest **official or first-party** checkpoint that stays useful on your hardware:

| Goal | Pick |
|------|------|
| Stay on Blackwell, serve later | Vendor **NVFP4** / MXFP4 when available |
| Max fidelity / re-quantize later | Official **FP8** (or BF16 if you need full precision) |
| Disk is tight | Smallest first-party quant that still runs on your stack |

Do **not** rely on random community GGUFs as the sole archive copy.

## Layout

```
/mnt/model-shelf/models/{lab}/{slug}/
  manifest.yaml
  nvfp4/   # or hf/ — match the checkpoint format
```

Examples:

- `nvidia/glm-5.2-nvfp4` ← `nvidia/GLM-5.2-NVFP4`
- `moonshotai/kimi-k3-…` ← whatever HF repo Moonshot publishes

## Download (straight to NAS)

```bash
ssh sparky '
LAB=nvidia
SLUG=glm-5.2-nvfp4
REPO=nvidia/GLM-5.2-NVFP4
FMT=nvfp4   # or hf
DEST=/mnt/model-shelf/models/$LAB/$SLUG
LOG=/opt/spark/logs/hf-archive-$SLUG.log
PIDFILE=/opt/spark/run/hf-archive-$SLUG.pid

mkdir -p "$DEST/$FMT"

cat > "$DEST/manifest.yaml" <<EOF
id: $LAB/$SLUG
hf_repo: $REPO
purpose: cold-archive
variants:
  - format: $FMT
    path: $FMT/
default_variant: $FMT
archived_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

# Resume-safe; lower workers are gentler on CIFS
nohup /opt/spark/venv/bin/hf download "$REPO" \
  --local-dir "$DEST/$FMT" \
  --max-workers 4 \
  >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
echo "started pid=$(cat $PIDFILE) log=$LOG"
'
```

Auth: `spark hf login --whoami` (token in `~/.cache/huggingface/token`). Ungated repos work without it; gated ones need accept-license + token.

## Monitor

```bash
ssh sparky '
SLUG=glm-5.2-nvfp4
PIDFILE=/opt/spark/run/hf-archive-$SLUG.pid
LOG=/opt/spark/logs/hf-archive-$SLUG.log
DEST=/mnt/model-shelf/models/nvidia/$SLUG

ps -p "$(cat $PIDFILE)" -o pid,etime,cmd || echo "not running"
tail -20 "$LOG"
du -sh "$DEST" "$DEST"/* 2>/dev/null
df -h /mnt/model-shelf
'
```

## Verify completeness

```bash
ssh sparky '
DEST=/mnt/model-shelf/models/nvidia/glm-5.2-nvfp4/nvfp4
# expect ~465G for GLM-5.2-NVFP4; shard count from HF card
du -sh "$DEST"
ls "$DEST"/*.safetensors 2>/dev/null | wc -l
test -f "$DEST/config.json" && test -f "$DEST/model.safetensors.index.json" && echo OK_META
'
```

Optional: re-run the same `hf download … --local-dir` — it skips complete files and fills gaps.

## Pull onto Sparky later (only if serving)

```bash
spark shelf pull nvidia/glm-5.2-nvfp4
```

That copies shelf → `/models`. Skip unless you have a machine that can load it.

## Kimi K3 checklist (reuse this runbook)

1. Wait for Moonshot’s public HF repo (weights targeted ~2026-07-27).
2. Prefer first-party MXFP4 / NVFP4-class if Blackwell-native; else official FP8.
3. Set `LAB` / `SLUG` / `REPO` / `FMT` and run the download block above.
4. Confirm `du` matches Hub size; keep `manifest.yaml`.
5. Do **not** `shelf pull` onto Sparky unless you intend to serve.

## Active archive log

| Model | HF repo | Shelf path | Approx size | Started |
|-------|---------|------------|-------------|---------|
| GLM-5.2 NVFP4 | `nvidia/GLM-5.2-NVFP4` | `nvidia/glm-5.2-nvfp4/nvfp4` | ~465 GB (complete) | 2026-07-22 → 2026-07-23 |
| Kimi K3 | _(pending)_ | _(pending)_ | ~1.4 TB? | — |
