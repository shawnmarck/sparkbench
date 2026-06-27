# Install

**Supported path:** `sudo bash install/spark-install <target>` from `/opt/spark` (or staging copy).

After `core`, the same orchestrator is available as `spark install <target>`.

```bash
sudo bash install/spark-install list      # targets + help
sudo bash install/spark-install status    # systemd + HTTP health
```

Env overrides (optional): `SPARK_ROOT`, `SPARK_STAGING`, `SPARK_USER`, `SPARK_HOST`, `SPARK_LAN_IP` — see `common.sh`.

Bundled targets (`core`, `gateway`) set `SPARK_INSTALL_BATCH=1` so modules defer nginx rewrites; the orchestrator calls `write_nginx_portal_site` once at the end. Standalone numbered scripts still refresh nginx immediately.

## Orchestrator targets

| Target | Purpose |
|--------|---------|
| `core` | Netdata + portal + CLI + `/models` layout + inventory refresh + GPU/shelf/HF/inference APIs + removal cron |
| `nas` | CIFS shelf mount + re-layout `/models` |
| `engine eugr\|llama\|ds4` | One GPU inference engine (mutually exclusive) |
| `gateway` | OpenAI-compatible `:9000/v1` proxy + client activity API |
| `openwebui` | Open WebUI dual-backend compose |
| `bootstrap` | Passwordless sudo for install scripts + Netdata/portal base |
| `agent` | Full passwordless sudo for automation (optional) |
| `restart inference-api` | Restart inference API only |
| `extras terminal\|shell\|lazydocker` | Maintainer convenience — not core SparkBench |

## Typical fresh order

```
bootstrap (optional) → core → engine eugr|llama|ds4 → gateway
nas (optional, any time after clone)
```

## Legacy numbered scripts

The scripts below are still idempotent and safe to run individually (agents, surgical fixes). Prefer `spark-install` for new setups.

### Bootstrap

| Script | Purpose |
|--------|---------|
| `00-grant-install-sudo.sh` | Passwordless sudo for `install/*.sh` and `install/spark-install` |
| `07-grant-agent-sudo.sh` | Agent sudo grants |

### Visibility

| Script | Purpose |
|--------|---------|
| `01-netdata-portal.sh` | Netdata + portal nginx base |

### Model shelf & inventory

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
| `20-spark-cli.sh` | **Unified `spark` CLI** — binary, completions, zsh `?` help |
| `21-hf-api.sh` | HF Explorer API (portal Explore tab) |

### Inference engines

| Script | Purpose |
|--------|---------|
| `13-llama-cpp-smoke.sh` | Build llama.cpp + `spark engine llama` |
| `14-openwebui-dual-backend.sh` | Open WebUI dual backend compose |
| `16-eugr-vllm-qwen36.sh` | eugr vLLM NVFP4 (`spark engine eugr`) |
| `22-ds4-dwarfstar.sh` | DwarfStar (ds4) cuda-spark build + `spark engine ds4` |

**Legacy (superseded — do not use on new installs):**

| Script | Notes |
|--------|--------|
| `15-vllm-openwebui-smoke.sh` | Pre–Phase 5 stock vLLM smoke; use `engine eugr` |
| `15b-sync-inference-compose.sh` | One-off compose sync; folded into eugr install path |
| `16b-fix-spark-eugr.sh` | One-off eugr script refresh; re-run `engine eugr` instead |

### Inference gateway & client activity

| Script | Purpose |
|--------|---------|
| `23-inference-gateway.sh` | Stable `:9000/v1` OpenAI proxy + activity JSONL |
| `24-client-activity-api.sh` | Activity API on `:8769` + nginx `/api/activity` |

### Convenience (extras)

| Script | Purpose |
|--------|---------|
| `06-kitty-terminal.sh` | Kitty terminal config |
| `08-zsh-powerlevel10k.sh` | Shell prompt |
| `09-lazydocker.sh` | lazydocker |

See also: `docs/reference/spark-cli.md`.
