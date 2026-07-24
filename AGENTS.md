# AGENTS.md — SparkBench (`/opt/spark`)

Quick orientation for coding agents. Humans: start at [README.md](README.md).

Extended workflows: [docs/guides/installation-instructions.md](docs/guides/installation-instructions.md) (also in `.claude/skills/sparkbench/` when cloned).

## What this is

Self-hosted model lab for DGX Spark (GB10): portal UI, model inventory, optional NAS shelf, inference control plane, benchmark harness. Public leaderboard at [sparkbench.dev](https://sparkbench.dev) is generated from this repo's data files.

Set `SPARK_HOST`, `SPARK_LAN_IP`, and optionally `SPARK_USER` (defaults to `$SUDO_USER` or `spark`) before install.

## Layout

```
/opt/spark/
├── portal/          Legacy static UI served at /
├── portal-v2/       Portal v2 SPA (Vite/React/shadcn) served at /v2/
├── scripts/         spark CLI + runtime (spark-inference.py, spark-hf.py, spark-install-api.py, …)
├── install/         spark-install orchestrator + modules/ — see install/INSTALL.md
├── data/            Catalog, verification, golden map; profiles/benchmarks are host-local
├── recipes/         Inference profile YAML (draft → testing → production)
├── docs/            guides/ runbooks/ reference/
└── services/        Optional compose (Open WebUI, bots)
```

**Portal v2 IA:** Catalog · Library · Recipes · Health · Add-ons · Setup (retires System|Models|Explore|Inference|Benchmaster tabs).

**Gitignored / host-local:** `portal/models.json`, `portal-v2/node_modules/`, `portal-v2/dist/`, `logs/`, `run/`, `venv/`, `host.env`, HF queue files under `data/`.

## Canonical docs

| Doc | Use when |
|-----|----------|
| `docs/reference/spark-cli.md` | Full CLI reference (agents: prefer `help` over `?`) |
| `install/INSTALL.md` | Install targets + module index |
| `docs/runbooks/sparky-live-sync.md` | Pulling code on a live box; skip-worktree |
| `docs/runbooks/new-model-golden-benchmark.md` | Onboard new models |
| `docs/guides/local-model-testing.md` | Bench queue, golden audit SOP |
| `docs/reference/inference-stack.md` | Gateway, profiles, recipes, APIs |
| `docs/reference/benchmark-standard.md` | Bench v2 policy |
| `docs/guides/model-shelf.md` | `/models` + optional NAS |

Smoke runbooks: `docs/runbooks/smoke-vllm-eugr.md`, `smoke-llamacpp.md`, `smoke-ds4.md`.

## Key URLs

Replace `sparky` with `$SPARK_HOST` or your hostname.

| Service | URL |
|---------|-----|
| Portal | http://sparky/ |
| Inference API | http://sparky/api/inference/status (→ :8767) |
| Install agent | http://sparky/api/install/status (→ :8771; mutations need X-Spark-Install-Token) |
| Gateway | http://sparky:9000/v1 |
| Activity | http://sparky/api/activity (→ :8769) |
| GPU / shelf | http://sparky/api/gpu , /api/shelf/status |
| Engines | vLLM :8000, llama.cpp :8081 |

## Rules

1. **One GPU engine at a time** — `spark engine eugr down` before `spark engine llama up` (and vice versa; ds4 same port as eugr).
2. **Shelf/mutation APIs are unauthenticated on LAN** — trusted homelab only; don't expose :80 WAN-side.
3. **Inventory build needs venv** — `/opt/spark/venv/bin/python scripts/spark-inventory-build.py`.
4. **Model paths** — local `/models`; optional NAS at `/mnt/model-shelf/models` when mounted.
5. **Recipes are auto-scaffolded** — extend the router in `spark-inference.py` + catalog `engine`/`capabilities`; don't hand-write YAML unless scaffold can't route (MoE, multimodal, DFlash, ds4, MTP). Fix `scaffold_error` on queue items by routing, not manual YAML bypass.
6. **Host-local runtime data** — `data/inference-profiles.yaml` and `data/inference-benchmarks.yaml` are skip-worktree; never `git checkout` them without backup. See `scripts/sparky-protect-runtime.sh`.

## spark CLI

Installed by `spark install core` (or `sudo bash install/spark-install core`). Minimal path: `/usr/local/bin/spark`.

**Agent workflow:** `spark inference status` → `spark inference list` → `spark inference up <id>` → poll status → work → `spark inference down` when freeing GPU.

Full command list: `docs/reference/spark-cli.md`. No shell: use HTTP URLs above.

## Install

```bash
sudo bash install/spark-install bootstrap   # optional: host.env + passwordless install
sudo bash install/spark-install core
sudo bash install/spark-install engine eugr   # or llama / ds4
sudo bash install/spark-install gateway
```

**Do not** run `spark-install core` on a live serving box — it restarts APIs and rewrites nginx. Use `spark-install module …` for surgical fixes (`install/INSTALL.md`).

Host identity: `install/host.env.example` → `/etc/spark/host.env` or `$SPARK_ROOT/host.env`. SMB creds: `/etc/spark/smb-credentials-models`.

## Inference API reload

`scripts/spark-inference-api.py` (:8767, `/api/inference/*`) reloads `spark-inference.py` each request — routine logic changes need no restart.

- **`spark-inference-api.py` changed:** `sudo bash install/spark-install restart inference-api`
- **Watch auto-restart:** installed with `spark-install core` (`modules/core/inference-api-watch.sh`)

## Golden audit & verify

**Policy:** `spark models verify set … works` only after bench v2 succeeds.

Workflow: `docs/runbooks/new-model-golden-benchmark.md`. Reports in `run/golden-audit-report.*`; map in `data/golden-recipes.yaml`.

**Common eugr recipe fixes:** `--language-model-only` when `config.json` has `"language_model_only": true`; Grok tool calls need `--enable-auto-tool-choice` + `--tool-call-parser qwen3_xml`.

## Code touchpoints

| Area | Where |
|------|--------|
| Nginx portal site | `install/common.sh` → `write_nginx_portal_site` (batch via `SPARK_INSTALL_BATCH` in orchestrator) |
| Portal shared grid UX | `portal/assets/spark-inventory-grid.js` (`window.SparkInventoryGrid`) |
| Explore / shortlist / inference UI | `portal/index.html` |
| HF explore queue + dedupe | `scripts/spark-hf.py` |
| Activity pipeline | Gateway appends `run/inference-activity.jsonl` → `spark-client-activity.py` :8769 → `/api/activity` |
| Optional chat UIs | `services/spark-bot/README.md` (gateway on :9000) |

## Threat model

LAN-trusted homelab. Secrets in `/etc/spark/` and env (`HF_TOKEN`) — never commit.
