# AGENT.md — SparkBench (`/opt/spark`)

Quick orientation for humans and coding agents working on this repo.

## What this is

**SparkBench** is the tool you clone and run on your own DGX Spark: portal UI, model inventory, NAS shelf sync, inference control plane, benchmark harness. **[sparkbench.dev](https://sparkbench.dev)** is the separate public site (leaderboard, model browser, benchmark results) generated from this repo's data files. Set `SPARK_HOST` / `SPARK_LAN_IP` env vars to match your machine (defaults: `sparky` / `192.168.0.101`).

## Layout

```
/opt/spark/
├── AGENT.md              This file
├── README.md             Repo homepage (GitHub + local)
├── portal/               Static UI (nginx :80)
│   ├── assets/           sparky-theme.js, oobe-nebula.js, nebula-tune.js, spark-inventory-grid.js
│   └── themes/           theme-b.css, theme-ui.css
├── scripts/              spark CLI + implementation scripts
├── install/              Idempotent sudo install scripts (see install/INSTALL.md)
├── data/                 model-catalog.yaml, model-verification.yaml, inference-profiles.yaml, ds4-dwarfstar.yaml
├── recipes/              Inference profile recipes (Phase 5)
├── docs/                 ROADMAP + guides/ runbooks/ reference/ examples/
└── services/             compose/yaml for inference UIs
```

**Staging:** edit on **techno** (`~/projects/sparky`), push to GitHub, deploy with `scripts/deploy-sparky.sh`. Runtime install is **`sparky:/opt/spark`** only.

**Generated (gitignored):** `portal/models.json`, `logs/`, `run/`, `venv/`

## Development workflow

Two valid sync paths — pick based on where you are editing.

```mermaid
flowchart TB
  subgraph techno["Techno (primary code path)"]
    A["Edit ~/projects/sparky"] --> B["git commit + push"]
    B --> C["./scripts/deploy-sparky.sh"]
    C --> D["sparky /opt/spark<br/>pull + runtime backup/restore"]
  end
  subgraph sparky["Sparky (local dev + on-box agent)"]
    E["Edit /opt/spark locally"] --> F{"Ready to sync?"}
    F --> G["git fetch origin"]
    G --> H["pull / rebase / merge"]
    H --> I["bash scripts/sparky-protect-runtime.sh"]
  end
  B --> G
  D --> J["Ops: inference, audit, logs"]
  I --> J
```

| Layer | Path | Role | Git on sparky |
|-------|------|------|---------------|
| Dev clone | `~/projects/sparky` on techno | Primary Cursor agent; commit, push | — |
| Remote | `github.com/shawnmarck/sparkbench` | Source of truth for **shared code** | — |
| Install | `/opt/spark` on sparky | Runtime + optional **local dev** | pull / rebase / merge |
| **Runtime data** | `/opt/spark/data/*.yaml` | Live audit/bench state | **`skip-worktree`** — never overwrite from git |

See **`docs/runbooks/sparky-live-sync.md`** for the full anti-regression model.

### Path A — techno agent (default for shared code)

1. Edit on techno → commit → push.
2. `./scripts/deploy-sparky.sh` (or `SKIP_PUSH=1` if already pushed).
3. Deploy backs up runtime YAML, pulls code, restores runtime, runs patches.

### Path B — agent on sparky (local dev on the box)

Local experimentation on sparky is OK. An agent **running on sparky** can sync when ready:

```bash
cd /opt/spark
bash scripts/sparky-protect-runtime.sh          # once, or before every sync
git fetch origin
git status                                        # review local commits + dirty tree
spark inference status                            # know what's live before recipe changes

# Pick one when ready (runtime YAML is skip-worktree / backed up):
git pull --ff-only origin main                  # no local commits — simplest
git rebase origin/main                          # local commits replayed on top of origin
git merge origin/main                           # merge origin into local branch
```

**Rules for sparky-local agents**

1. **Protect runtime data first** — `bash scripts/sparky-protect-runtime.sh`. Never `git checkout -- data/*.yaml` from origin.
2. **Never `git stash -u`** on `recipes/` or `services/` — can delete host-only files (learned the hard way).
3. **Check active inference** — `spark inference status` before changing recipes/services for the loaded profile.
4. **Local commits on sparky are a staging area** — cherry-pick or re-apply on techno and push to GitHub when the change is real; don't let sparky-only commits drift forever.
5. **Prefer ff-only pull** when sparky has no local commits; use rebase or merge only when you intentionally have local work to keep.
6. **Vendor/build drift** (`vendor/`, `bin/llama-*`) — ignore or reset to origin; not shared via git.

**Rules for techno agents**

1. **Shared code** (scripts, recipes, portal, docs): change on techno → commit → push → `./scripts/deploy-sparky.sh`. Do not `scp` except emergencies (then commit immediately).
2. **Ops** (inference up/down, golden audit, logs): `ssh sparky '…'` or sparky-local agent.
3. **Runtime data** on sparky: owned by audits/bench — never reset from git on techno deploy without backup (deploy handles this automatically).
4. **Model recipes/services must be in git** before relying on deploy from techno.
5. After techno deploy: `./scripts/deploy-sparky.sh --status`.

```bash
# From ~/projects/sparky on techno
./scripts/deploy-sparky.sh --status
./scripts/deploy-sparky.sh
SKIP_PUSH=1 ./scripts/deploy-sparky.sh
```

Emergency stash on sparky from a deploy: `ssh sparky 'cd /opt/spark && git stash list'`.


## Canonical docs (read these)

| Doc | Use when |
|-----|----------|
| `docs/ROADMAP.md` | **The plan** — vision, Model Lab loop, backlog queue |
| `docs/roadmap/README.md` | **Main agent workflow** — techno, one PR per task, sequential merge |
| `docs/roadmap/tasks/*.md` | Task specs (requirements, acceptance criteria, test plan) |
| `README.md` | Repo homepage + doc index |
| `docs/guides/model-shelf.md` | `/models` + NAS shelf layout |
| `docs/guides/model-picks.md` | Why each model is in the catalog |
| `docs/runbooks/smoke-vllm-eugr.md` | eugr vLLM validation (`spark engine eugr`) |
| `docs/runbooks/smoke-llamacpp.md` | llama.cpp validation (`spark engine llama`) |
| `docs/runbooks/smoke-ds4.md` | DwarfStar ds4 validation (`spark engine ds4`) |
| `docs/runbooks/new-model-golden-benchmark.md` | Onboard new models: golden map, audit, ctx viability |
| `docs/guides/local-model-testing.md` | Bench queue SOP, golden audit, stack fixes learned |
| `docs/runbooks/sparky-live-sync.md` | **Sparky live sync** — runtime data vs code, skip-worktree |
| `docs/reference/inference-stack.md` | Phase 5 technical spec |
| `install/INSTALL.md` | Install script index + order |

`docs/ROADMAP.md` is the single source of truth for phases. Other docs are guides, runbooks, or specs — see `README.md`.

## Key URLs

| Service | URL |
|---------|-----|
| Portal | http://sparky/ |
| Models | http://sparky/models.html |
| Metrics API | http://sparky/api/gpu |
| Inference API | http://sparky/api/inference/status (nginx → :8767) |
| **Inference gateway** | http://sparky:9000/v1 (OpenAI-compatible; aliases + auto-switch) |
| Activity API | http://sparky/api/activity (nginx → :8769; per-client summary + recent sessions) |
| Shelf API | http://sparky/api/shelf/status |
| vLLM | http://sparky:8000/v1 |
| llama.cpp | http://sparky:8081/v1 |
| Open WebUI | http://sparky:3000 |
| Hermes UI | http://sparky:9119 |
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
7. **Recipes are auto-scaffolded** — after download, `spark-hf` queue worker calls `scaffold_recipe` / specialized scaffolds in `spark-inference.py`. Do not hand-write recipe YAML unless scaffold cannot route the architecture (MoE, multimodal, DFlash, ds4, MTP). Extend the scaffold router in code + catalog `engine`/`capabilities` when adding new engine types. Failed scaffolds surface as `scaffold_error` on queue items — fix routing, don't bypass with manual YAML.

## `spark` CLI (humans + agents)

**Canonical reference:** `docs/reference/spark-cli.md`

Single command on PATH: **`spark`** (`install/20-spark-cli.sh`). Legacy `spark-*` bins removed — see `scripts/legacy/README.md`.

| Who | How to discover | How to run |
|-----|-----------------|------------|
| **Human** (zsh on sparky) | `spark ?`, `spark inf help`, Tab completion | Interactive shell |
| **Coding agent** | `spark --help`, `spark inference help`, `spark inference list` | Non-interactive; prefer `help` over `?` |
| **No shell** | HTTP APIs | `http://sparky/api/inference/status`, `/api/gpu`, `/api/shelf/status` |

```bash
spark status
spark inference list       # enabled profiles — agents: run before spark inference up
spark inference status     # active profile + engine health
spark inference up <id>    # switch profile (evicts current)
spark inference bench      # measure tok/s on active profile
spark recipe list          # Model Lab recipes (draft/testing/production)
spark models inventory     # regenerate portal/models.json
spark models verify set <lab/slug> works
spark shelf pull <lab/slug>
spark engine eugr status   # low-level vLLM (direct)
spark engine llama status  # low-level llama.cpp (direct)
spark gpu                  # metrics JSON (same schema as /api/gpu)
curl http://sparky/api/inference/status   # JSON for portal/gateway
```

**Agents:** use `/usr/local/bin/spark` if `PATH` is minimal; check exit codes; one GPU engine at a time. Do not rely on Tab or unquoted `?`.

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

`scripts/spark-inference-api.py` is a thin HTTP shell on **:8767** (proxied as `http://sparky/api/inference/*`). It delegates every GET/POST/PATCH to `scripts/spark-inference.py:api_dispatch()` and **reloads the core module on each request** — bench, switch, recipe lifecycle, and history routes all live in `spark-inference.py`.

- **Routine changes to `spark-inference.py`:** no restart; hit any `/api/inference/*` endpoint after saving.
- **Changes to `spark-inference-api.py` itself:** restart the service — `sudo bash install/19-inference-api-restart.sh` (or `sudo systemctl restart spark-inference-api`).
- **Auto-restart on script save:** `sudo bash install/18-inference-api-watch.sh` (systemd path unit; chained from `17`).

## Golden audit & new models

**Policy:** `spark models verify set … works` only after **bench v2** succeeds (`docs/reference/benchmark-standard.md`).

```bash
# Full fleet
nohup /opt/spark/venv/bin/python3 scripts/golden-inventory-audit.py \
  --reset-verify --skip-shelf >> logs/golden-audit.log 2>&1 &

# New models only
scripts/spark-new-model-golden.sh qwen/qwen-agentworld-35b-a3b empero-ai/qwythos-9b-claude-mythos-5-1m
```

Reports: `run/golden-audit-report.json` + `.md`. Golden map: `data/golden-recipes.yaml`.

**Common eugr fixes (Qwen agents / Grok):**

- Text-only MM checkpoint: `--language-model-only` when `config.json` has `"language_model_only": true` (AgentWorld).
- Grok `tool_choice: auto`: `--enable-auto-tool-choice` + `--tool-call-parser qwen3_xml` on eugr YAML.

**Context viability (load + smoke, no bench):** `scripts/ctx-viability-test.sh`, `scripts/update-recipe-ctx.py` — see runbook.

## Hermes spark-bot

Compose + deploy live under `hermes/` in this repo; runtime on host is **`/opt/hermes`** (outside `/opt/spark`). Do **not** stop Model Lab inference for routine bot work. See `hermes/spark-bot/AGENTS.md`, deploy via `hermes/scripts/deploy-spark-bot.sh`.

## Threat model (short)

- LAN-trusted homelab; mutation APIs on :80 have no auth.
- Secrets: `/etc/spark/smb-credentials-models`, `HF_TOKEN` in env — never commit.