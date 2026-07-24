# Install

**Supported path:** `sudo bash install/spark-install <target>` from `/opt/spark` (or staging copy).

After `core`, the same orchestrator is available as `spark install <target>`.

```bash
sudo bash install/spark-install list      # targets + help
sudo bash install/spark-install status    # systemd + HTTP health
```

Env overrides (optional): `SPARK_ROOT`, `SPARK_STAGING`, `SPARK_USER`, `SPARK_HOST`, `SPARK_LAN_IP` — see `common.sh`.

Host identity: copy `install/host.env.example` → `/etc/spark/host.env` or `/opt/spark/host.env` (gitignored). Or run `spark-install bootstrap`.

Bundled targets (`core`, `gateway`) set `SPARK_INSTALL_BATCH=1` so modules defer nginx rewrites; the orchestrator calls `write_nginx_portal_site` once at the end.

## Orchestrator targets

| Target | Purpose |
|--------|---------|
| `quickstart` | `bootstrap` + `core` in one target (portal, APIs, CLI — no GPU engine) |
| `core` | Netdata + portal + CLI + `/models` layout + inventory refresh + GPU/shelf/HF/inference/operator APIs + removal cron |
| `nas` | CIFS shelf mount + re-layout `/models` |
| `engine eugr\|llama\|ds4` | One GPU inference engine (mutually exclusive) |
| `gateway` | OpenAI-compatible `:9000/v1` proxy + client activity API |
| `openwebui` | Open WebUI dual-backend compose |
| `hermes` | Spark embedded operator backed by Hermes and an out-of-band provider |
| `bootstrap` | `host.env` + passwordless sudo for install + Netdata/portal base |
| `agent` | Full passwordless sudo for automation (optional) |
| `restart inference-api` | Restart inference API only (ops shortcut) |
| `module <path>` | Run one module under `install/modules/` (surgical fix) |
| `extras terminal\|shell\|lazydocker\|agent-skill` | Maintainer convenience — `agent-skill` copies harness skill to `~/.claude/skills` and `~/.cursor/skills` |

## Typical fresh order

```
bootstrap (optional) → quickstart (or core) → engine eugr|llama|ds4 → gateway
# or: curl -fsSL …/scripts/bootstrap-sparkbench.sh | sudo bash  →  engine  →  gateway
nas (optional, any time after clone)
```

## Module layout (`install/modules/`)

| Path | Purpose |
|------|---------|
| `bootstrap/host-env.sh` | Create `/etc/spark/host.env` from example when missing |
| `bootstrap/grant-install-sudo.sh` | Passwordless sudo for `spark-install` + modules |
| `bootstrap/grant-agent-sudo.sh` | Full passwordless sudo for automation |
| `core/portal-base.sh` | Netdata + portal nginx base |
| `core/cli.sh` | Unified `spark` CLI on PATH |
| `core/models-layout.sh` | `/models` workspace (+ shelf skeleton when NAS mounted) |
| `core/shelf-hf-tools.sh` | `spark shelf`, `spark hf login`, `hf` CLI |
| `core/models-inventory.sh` | Catalog sync, inventory builder, portal pages |
| `core/inventory-refresh.sh` | Timer + inotify inventory refresh |
| `core/gpu-api.sh` | GPU metrics API + nginx |
| `core/shelf-api.sh` | Shelf/model HTTP APIs |
| `core/hf-api.sh` | HF Explorer API (portal Explore tab) |
| `core/inference-api.sh` | Inference control API |
| `core/benchmaster-api.sh` | Benchmaster queue control API (:8770) |
| `core/install-api.sh` | Privileged install agent API (:8771) for portal Setup |
| `core/operator-api.sh` | Loopback Spark operator bridge (:8772) |
| `core/inference-api-watch.sh` | Auto-restart inference API on script changes |
| `core/inference-api-restart.sh` | Restart inference API only |
| `core/removal-cron.sh` | Nightly queued local model purge |
| `optional/nas-mount.sh` | CIFS mount `/mnt/model-shelf` |
| `optional/openwebui.sh` | Open WebUI dual-backend compose |
| `optional/hermes.sh` | Preservation-safe Hermes runtime and typed SparkBench MCP tools |
| `engines/eugr-vllm.sh` | eugr vLLM NVFP4 |
| `engines/llama-cpp.sh` | llama.cpp GGUF build |
| `engines/ds4-dwarfstar.sh` | DwarfStar (ds4) cuda-spark |
| `gateway/inference-gateway.sh` | `:9000/v1` OpenAI proxy + activity JSONL |
| `gateway/client-activity.sh` | Activity API `:8769` + nginx `/api/activity` |
| `extras/*` | Maintainer convenience (kitty, p10k, lazydocker, agent-skill) |

**Surgical module run** (when `spark-install core` is too broad on a live box):

```bash
sudo bash install/spark-install module core/inference-api-restart.sh
# equivalent: sudo bash install/modules/core/inference-api-restart.sh
```

See also: `docs/reference/spark-cli.md`, `docs/runbooks/sparky-live-sync.md`.
