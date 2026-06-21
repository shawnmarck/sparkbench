# AGENT.md — Sparky homelab (`/opt/spark`)

Quick orientation for humans and coding agents working on this repo.

## What this is

Private dashboard + ops tooling for a **DGX Spark** (`sparky`, `192.168.0.101`): portal UI, model inventory, NAS shelf sync, inference smoke stacks.

## Layout

```
/opt/spark/
├── AGENT.md              This file
├── README.md             Repo homepage (GitHub + local)
├── portal/               Static UI (nginx :80)
│   ├── assets/           sparky-theme.js, oobe-nebula.js, nebula-tune.js
│   └── themes/           theme-b.css, theme-ui.css
├── scripts/              CLIs + APIs (spark-*)
├── install/              Idempotent sudo install scripts (see install/INSTALL.md)
├── data/                 model-catalog.yaml, model-verification.yaml, inference-profiles.yaml
├── recipes/              Inference profile recipes (Phase 5)
├── docs/                 ROADMAP + guides/ runbooks/ reference/ examples/
└── services/             compose/yaml for inference UIs
```

**Staging:** edits often land in `~/spark` first; install scripts promote to `/opt/spark`.

**Generated (gitignored):** `portal/models.json`, `logs/`, `run/`, `venv/`

## Canonical docs (read these)

| Doc | Use when |
|-----|----------|
| `docs/ROADMAP.md` | **The plan** — phases, status, next steps |
| `README.md` | Repo homepage + doc index |
| `docs/guides/model-shelf.md` | `/models` + NAS shelf layout |
| `docs/guides/model-picks.md` | Why each model is in the catalog |
| `docs/runbooks/smoke-vllm-eugr.md` | eugr vLLM validation (`spark engine eugr`) |
| `docs/runbooks/smoke-llamacpp.md` | llama.cpp validation (`spark engine llama`) |
| `docs/reference/inference-stack.md` | Phase 5 technical spec |
| `install/INSTALL.md` | Install script index + order |

`docs/ROADMAP.md` is the single source of truth for phases. Other docs are guides, runbooks, or specs — see `README.md`.

## Key URLs

| Service | URL |
|---------|-----|
| Portal | http://sparky/ |
| Models | http://sparky/models.html |
| Metrics API | http://sparky/api/gpu |
| Inference API | http://sparky/api/inference/status |
| Shelf API | http://sparky/api/shelf/status |
| vLLM | http://sparky:8000/v1 |
| llama.cpp | http://sparky:8081/v1 |
| Open WebUI | http://sparky:3000 |
| Netdata | http://sparky:19999/v3/ |

## Portal theme (optional)

**Theme B** — DGX OOBE-style canvas nebula behind System and Models. Opt-in via the constellation button in the nav (persists in `localStorage` key `sparky-theme`, or `?theme=b` on first load). Default theme unchanged.

- JS: `portal/assets/sparky-theme.js` (toggle, iframe sync), `portal/assets/oobe-nebula.js` (canvas)
- CSS: `portal/themes/theme-b.css`, `portal/themes/theme-ui.css`
- Dev tuning panel: gear icon (bottom-left) when Theme B is on; hide with `?nebula-tune=0`
- Models in portal iframe: parent nav toggle syncs theme via `postMessage`; no duplicate floating toggle when embedded

## Rules agents should know

1. **One GPU engine at a time** — `spark engine eugr down` before `spark engine llama up` (and vice versa).
2. **Do not re-run `install/05` blindly** — it writes nginx via `common.sh` (safe now), but always prefer `install/common.sh` helper.
3. **Shelf APIs are unauthenticated on LAN** — OK for trusted home LAN only; don't expose port 80 WAN-side.
4. **Inventory build needs venv** — `/opt/spark/venv/bin/python scripts/spark-inventory-build.py` (HF API).
5. **Model paths** — local `/models`, NAS `/mnt/model-shelf/models`.
6. **Bake-off UIs removed** — no Rookery / vLLM Studio; Phase 5 is `spark inference` + `recipes/`.

## Common commands

Single CLI: **`spark`** (`install/20-spark-cli.sh`). Legacy `spark-*` names are not on PATH — see `scripts/legacy/README.md`.

```bash
spark status
spark inference list       # enabled profiles
spark inference status     # active profile + engine health
spark inference up <id>    # switch profile (evicts current)
spark inference bench      # measure tok/s on active profile
spark recipe list          # Model Lab recipes (draft/testing/production)
spark models inventory     # regenerate portal/models.json
spark models verify set <lab/slug> works
spark shelf pull <lab/slug>
spark engine eugr status   # low-level vLLM (direct)
spark engine llama status  # low-level llama.cpp (direct)
spark gpu                  # one-shot metrics JSON
curl http://sparky/api/inference/status   # JSON for portal/gateway
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

Inference (pick what you need): `16-eugr-vllm-qwen36.sh`, `13-llama-cpp-smoke.sh`.

## Sudo

Passwordless sudo for `install/*.sh` only (via `00-grant-install-sudo.sh`). Optional full agent sudo: `install/07-grant-agent-sudo.sh`.

## Inference API reload (agents)

`spark-inference-api` **hot-reloads** `scripts/spark-inference.py` on each request when the file changes — new routes and logic apply without `systemctl restart`.

- **Routine code changes:** no restart; hit any `/api/inference/*` endpoint after editing `spark-inference.py`.
- **Full process restart** (rare — e.g. first deploy of hot-reload shell, port stuck):  
  `sudo bash install/19-inference-api-restart.sh` (needs `00-grant-install-sudo.sh` once).
- **Auto-restart on script save:** `sudo bash install/18-inference-api-watch.sh` (systemd path unit; chained from `17`).

## Threat model (short)

- LAN-trusted homelab; mutation APIs on :80 have no auth.
- Secrets: `/etc/spark/smb-credentials-models`, `HF_TOKEN` in env — never commit.