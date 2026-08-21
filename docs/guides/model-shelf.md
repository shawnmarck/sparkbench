# Model shelf layout

Same tree on the Spark box and the optional QNAP shelf.

## Paths

| Role | Path |
|------|------|
| Spark workspace (download + run) | `/models` |
| NAS backup (mirror) | `/mnt/model-shelf/models` |
| Partial downloads (Spark) | `/models/_incoming` |
| Drops for later (NAS) | `/mnt/model-shelf/models/_incoming` |

Install the mount with `sudo bash install/spark-install nas`. Creds: `/etc/spark/smb-credentials-models`. Local `/models` works without a shelf.

## Directory layout

```
{lab}/{model-version}/
  manifest.yaml
  gguf/           # llama.cpp — loose files or gguf/{Q4_K_M}/ bundles
  hf/             # Hugging Face safetensors for vLLM
  nvfp4/          # GB10-optimized exports
  fp8/            # official FP8 checkpoints
  awq/  gptq/     # optional
```

Example:

```
/models/google/gemma-4-26b-a4b-it/
  manifest.yaml
  gguf/
    gemma-4-26b-a4b-Q4_K_M.gguf
  hf/
    config.json
    model.safetensors.index.json
```

## Workflow

1. **Download to Spark** → `/models/_incoming/` or straight into the model tree
2. **Smoke test** (`spark inference up <profile>`)
3. **Back up to shelf** (Spark → NAS):

   ```bash
   spark shelf push google/gemma-4-26b-a4b-it
   ```

4. **Restore from shelf**:

   ```bash
   spark shelf pull google/gemma-4-26b-a4b-it
   ```

Default direction is Spark → shelf. Pull only to restore or to fetch a model that is not on local disk.

Recipes point at `/models/...`. If a stack wants another path, symlink. Do not fork a second tree.

## manifest.yaml (per model)

```yaml
id: google/gemma-4-26b-a4b-it
hf_repo: google/gemma-4-26b-a4b-it
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

## Background push (rate-limited)

Large backups can run without saturating the LAN:

```bash
# ~200 Mbps cap, low CPU/IO priority, log: /opt/spark/logs/shelf-push-latest.log
spark shelf push --all --background --bwlimit 200
spark shelf push --status
```

`--bwlimit` is megabits/sec (rsync KiB/s under the hood). Omit for unlimited.

## Commands

| Command | Purpose |
|---------|---------|
| `spark shelf push MODEL` | Backup one model to NAS |
| `spark shelf push --all` | Push all models (skips `_incoming`) |
| `spark shelf pull MODEL` | Restore one model from NAS |
| `spark shelf status` | Mount + last job |
| `--dry-run` | Preview rsync |

Legacy wrappers `spark-shelf-push` / `spark-shelf-pull` are not on PATH. Use `spark shelf`.

## Related

- Layout: `sudo bash /opt/spark/install/spark-install core` (or `module core/models-layout.sh`)
- NAS mount: `sudo bash /opt/spark/install/spark-install nas`
- Cold archive (NAS only, do not land on Sparky): [frontier-model-archive.md](../runbooks/frontier-model-archive.md)
