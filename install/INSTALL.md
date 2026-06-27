# Install script index

Run with `sudo bash install/<script>.sh` from `/opt/spark` (or staging copy).

Env overrides (optional): `SPARK_ROOT`, `SPARK_STAGING`, `SPARK_USER`, `SPARK_HOST`, `SPARK_LAN_IP` — see `common.sh`.

## Bootstrap

| Script | Purpose |
|--------|---------|
| `00-grant-install-sudo.sh` | Passwordless sudo for `install/*.sh` |
| `07-grant-agent-sudo.sh` | Agent sudo grants |

## Visibility

| Script | Purpose |
|--------|---------|
| `01-netdata-portal.sh` | Netdata + portal nginx base |

## Model shelf & inventory

| Script | Purpose |
|--------|---------|
| `02-model-shelf-mount.sh` | **Optional** CIFS mount `/mnt/model-shelf` |
| `03-model-shelf-layout.sh` | `/models` workspace (+ shelf skeleton when NAS is mounted) |
| `03a-shelf-hf-tools.sh` | `spark shelf push/pull`, `spark hf login`, `hf` CLI |
| `04-model-inventory.sh` | Catalog, inventory builder, portal pages |
| `05-model-inventory-auto-refresh.sh` | Timer + inotify refresh; nginx (via `common.sh`) |
| `10-portal-gpu-widget.sh` | `spark gpu` API + nginx |
| `11-model-shelf-api.sh` | Shelf/model APIs + removal cron deps |
| `12-model-removal-cron.sh` | Nightly queued local model purge |
| `17-inference-api.sh` | Inference control API + nginx route |
| `18-inference-api-watch.sh` | Restart API when inference scripts change |
| `19-inference-api-restart.sh` | Restart inference API only (agent-friendly) |
| `20-spark-cli.sh` | **Unified `spark` CLI** — binary, completions, zsh `?` help; removes legacy `spark-*` bins. See `docs/reference/spark-cli.md` |

## Inference engines

| Script | Purpose |
|--------|---------|
| `15-vllm-openwebui-smoke.sh` | Stock vLLM compose smoke (legacy) |
| `15b-sync-inference-compose.sh` | Sync compose files to `/opt/spark/services` |
| `16-eugr-vllm-qwen36.sh` | eugr vLLM NVFP4 (`spark engine eugr`) |
| `16b-fix-spark-eugr.sh` | eugr stack fixes |
| `13-llama-cpp-smoke.sh` | Build llama.cpp + `spark engine llama` |
| `14-openwebui-dual-backend.sh` | Open WebUI dual backend compose |

## Inference gateway & client activity

| Script | Purpose |
|--------|---------|
| `23-inference-gateway.sh` | Stable `:9000/v1` OpenAI proxy + systemd (`spark-inference-gateway.service`); instruments `chat/completions` to `run/inference-activity.jsonl` |
| `24-client-activity-api.sh` | Activity API on `:8769` + systemd + nginx `/api/activity`; reads gateway JSONL for the Portal System-tab widget |

## Convenience

| Script | Purpose |
|--------|---------|
| `06-kitty-terminal.sh` | Kitty terminal config |
| `08-zsh-powerlevel10k.sh` | Shell prompt |
| `09-lazydocker.sh` | lazydocker |

## Typical fresh order

```
03 → 04 → 05 → 10 → 11 → 12          # core portal + /models (no NAS required)
02 → 03                              # optional: add NAS shelf mirror
16 (vLLM) and/or 13 (llama.cpp) — one GPU engine at a time
20 (unified `spark` CLI — run once, or chained from 17)
23 → 24 (stable gateway :9000/v1, then client activity widget) — run after an engine is up
```
- `22-ds4-dwarfstar.sh` — DwarfStar (ds4) cuda-spark build + `spark engine ds4`
