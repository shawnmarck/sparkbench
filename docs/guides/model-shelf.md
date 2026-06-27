# Model shelf layout

Canonical organization for models on **Spark** and **QNAP shelf**. Same tree on both sides.

## Paths

| Role | Path |
|------|------|
| Spark workspace (download + run) | `/models` |
| NAS backup (mirror) | `/mnt/model-shelf/models` |
| Partial downloads (Spark) | `/models/_incoming` |
| Drops for later (NAS / Hermes) | `/mnt/model-shelf/models/_incoming` |

## Directory layout

```
{lab}/{model-version}/
  manifest.yaml
  gguf/           # llama.cpp — quant files or gguf/{Q4_K_M}/ bundles
  hf/             # HuggingFace safetensors layout for vLLM
  nvfp4/          # GB10-optimized exports
  awq/  gptq/     # optional
```

### Example

```
/models/google/gemma-4-26b-a4b/
  manifest.yaml
  gguf/
    gemma-4-26b-a4b-Q4_K_M.gguf
    gemma-4-26b-a4b-Q6_K.gguf
  hf/
    config.json
    model.safetensors.index.json
```

## Workflow

1. **Download to Spark** → `/models/_incoming/` or directly into the model tree
2. **Smoke test** on GB10 (CLI / inference UI)
3. **Back up to shelf** (Spark → NAS):
   ```bash
   spark-shelf-push google/gemma-4-26b-a4b
   ```
4. **Restore from shelf** when needed:
   ```bash
   spark-shelf-pull google/gemma-4-26b-a4b
   ```

Default sync direction: **Spark → shelf**. Pull from shelf only when restoring or fetching a model not on local disk.

## manifest.yaml (per model)

Place at `{lab}/{model-version}/manifest.yaml`:

```yaml
id: google/gemma-4-26b-a4b
hf_repo: google/gemma-4-26b-a4b   # optional
license: gemma
variants:
  - format: gguf
    quant: Q4_K_M
    files: [gguf/gemma-4-26b-a4b-Q4_K_M.gguf]
    engine: llamacpp
  - format: hf
    path: hf/
    engine: vllm
default_variant: gguf/Q4_K_M
```

## Inference stacks

Recipes should point at `/models/...` directly. If a stack expects a different path, use a symlink:

```bash
ln -s /models ~/models              # example shim
```

Avoid reorganizing for stack defaults; keep one canonical tree.


## Background push (rate-limited)

Large backups can run in the background without saturating the LAN:

```bash
# ~200 Mbps cap, low CPU/IO priority, logs to /opt/spark/logs/shelf-push-latest.log
spark-shelf-push --all --background --bwlimit 200

spark-shelf-push --status    # running? tail of log
```

`--bwlimit` is megabits/sec (rsync KiB/s under the hood). Omit for unlimited.

## Commands

| Command | Purpose |
|---------|---------|
| `spark-shelf-push MODEL` | Backup one model to NAS |
| `spark-shelf-push --all` | Push all models (excludes `_incoming`) |
| `spark-shelf-pull MODEL` | Restore one model from NAS |
| `--dry-run` | Preview rsync on either command |

## Related

- Install: `/opt/spark/install/03-model-shelf-layout.sh`
- NAS mount: `/opt/spark/install/02-model-shelf-mount.sh`
