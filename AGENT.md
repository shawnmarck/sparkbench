# AGENT.md — Sparky homelab (`/opt/spark`)

Quick orientation for humans and coding agents working on this repo.

## What this is

Private dashboard + ops tooling for a **DGX Spark** (`sparky`, `192.168.0.101`): portal UI, model inventory, NAS shelf sync, inference smoke stacks.

## Layout

```
/opt/spark/
├── AGENT.md              This file
├── README.md             → docs/README.md
├── portal/               Static UI (nginx :80)
├── scripts/              CLIs + APIs (spark-*)
├── install/              Idempotent sudo install scripts (see install/INSTALL.md)
├── data/                 model-catalog.yaml, model-verification.yaml
├── docs/                 Human docs (ROADMAP, BAKE-OFF, smoke tests)
└── services/             compose/yaml for inference UIs
```

**Staging:** edits often land in `~/spark` first; install scripts promote to `/opt/spark`.

**Generated (gitignored):** `portal/models.json`, `logs/`, `run/`, `venv/`

## Canonical docs (read these)

| Doc | Use when |
|-----|----------|
| `docs/ROADMAP.md` | Phase status, URLs, what's done |
| `docs/BAKE-OFF.md` | vLLM Studio vs Rookery (Rookery disqualified) |
| `docs/MODEL-SHELF.md` | `/models` + NAS shelf layout |
| `docs/INFERENCE-SMOKE.md` | eugr vLLM (`spark-eugr`) |
| `docs/LLAMACPP-SMOKE.md` | native llama.cpp (`spark-llama`) |
| `install/INSTALL.md` | Install script index + order |

`docs/README.md` is the doc hub. Ignore stale "not installed" remnants if they disagree with ROADMAP.

## Key URLs

| Service | URL |
|---------|-----|
| Portal | http://sparky/ |
| Models | http://sparky/models.html |
| Metrics API | http://sparky/api/gpu |
| Shelf API | http://sparky/api/shelf/status |
| vLLM | http://sparky:8000/v1 |
| llama.cpp | http://sparky:8081/v1 |
| Open WebUI | http://sparky:3000 |
| vLLM Studio | http://sparky:3080 |
| Netdata | http://sparky:19999/v3/ |

## Rules agents should know

1. **One GPU engine at a time** — `spark-eugr down` before `spark-llama up` (and vice versa).
2. **Do not re-run `install/05` blindly** — it writes nginx via `common.sh` (safe now), but always prefer `install/common.sh` helper.
3. **Shelf APIs are unauthenticated on LAN** — OK for trusted home LAN only; don't expose port 80 WAN-side.
4. **Inventory build needs venv** — `/opt/spark/venv/bin/python scripts/spark-inventory-build.py` (HF API).
5. **Model paths** — local `/models`, NAS `/mnt/model-shelf/models`.

## Common commands

```bash
spark-eugr status          # vLLM NVFP4 stack
spark-llama status         # llama.cpp server
spark-shelf-push --help    # NAS backup
spark-shelf-pull           # fetch from NAS
spark-inventory-build      # regenerate portal/models.json
spark-model-verify         # CLI verify / removal flags
spark-gpu-metrics          # one-shot metrics JSON
```

## Install (typical order)

See `install/INSTALL.md` for full index. Core path:

```bash
sudo bash install/02-model-shelf-mount.sh
sudo bash install/03-model-shelf-layout.sh
sudo bash install/04-model-inventory.sh
sudo bash install/05-model-inventory-auto-refresh.sh
sudo bash install/10-portal-gpu-widget.sh
sudo bash install/11-model-shelf-api.sh
```

Inference (pick what you need): `16-eugr-vllm-qwen36.sh`, `13-llama-cpp-smoke.sh`, `17-vllm-studio.sh`.

## Sudo

Passwordless sudo for `install/*.sh` only (via `00-grant-install-sudo.sh`). `spark-vllm-studio` may need sudo for systemctl.

## Threat model (short)

- LAN-trusted homelab; mutation APIs on :80 have no auth.
- Secrets: `/etc/spark/smb-credentials-models`, `HF_TOKEN` in env — never commit.