# AGENTS.md — SparkBench (`/opt/spark`)

Quick orientation for humans and coding agents working on this repo.

## What this is

**SparkBench** is the tool you clone and run on your own DGX Spark: portal UI, model inventory, optional NAS shelf sync, inference control plane, benchmark harness. **[sparkbench.dev](https://sparkbench.dev)** is the separate public site (leaderboard, model browser, benchmark results) generated from this repo's data files.

Set `SPARK_HOST`, `SPARK_LAN_IP`, and optionally `SPARK_USER` (defaults to `$SUDO_USER` or `spark`) before running install scripts.

## Layout

```
/opt/spark/
├── AGENTS.md             This file
├── README.md             Repo homepage (GitHub + local)
├── portal/               Static UI (nginx :80)
│   ├── assets/           sparky-theme.js, oobe-nebula.js, nebula-tune.js, spark-inventory-grid.js
│   └── themes/           theme-b.css, theme-ui.css
├── scripts/              spark CLI + implementation scripts
├── install/              Idempotent sudo install scripts (see install/INSTALL.md)
├── data/                 model-catalog.yaml, model-verification.yaml, inference-profiles.yaml, ds4-dwarfstar.yaml
├── recipes/              Inference profile recipes (Phase 5)
├── docs/                 guides/ runbooks/ reference/ examples/
└── services/             compose/yaml for inference UIs
```

**Generated (gitignored):** `portal/models.json`, `logs/`, `run/`, `venv/`

## Canonical docs (read these)

| Doc | Use when |
|-----|----------|
| `README.md` | Repo homepage + doc index |
| `docs/guides/model-shelf.md` | `/models` + optional NAS shelf layout |
| `docs/guides/model-picks.md` | Why each model is in the catalog |
| `docs/runbooks/smoke-vllm-eugr.md` | eugr vLLM validation (`spark engine eugr`) |
| `docs/runbooks/smoke-llamacpp.md` | llama.cpp validation (`spark engine llama`) |
| `docs/runbooks/smoke-ds4.md` | DwarfStar ds4 validation (`spark engine ds4`) |
| `docs/runbooks/new-model-golden-benchmark.md` | Onboard new models: golden map, audit, ctx viability |
| `docs/guides/local-model-testing.md` | Bench queue SOP, golden audit, stack fixes learned |
| `docs/runbooks/sparky-live-sync.md` | Runtime data vs code, skip-worktree |
| `docs/reference/inference-stack.md` | Phase 5 technical spec |
| `install/INSTALL.md` | Install script index + order |

## Key URLs

Replace `sparky` with your machine's hostname or `$SPARK_HOST`.

| Service | URL |
|---------|-----|
| Portal | http://sparky/ |
| Models | http://sparky/models.html |
| Metrics API | http://sparky/api/gpu |
| Inference API | http://sparky/api/inference/status (nginx → :8767) |
| **Inference gateway** | http://sparky:9000/v1 (OpenAI-compatible; aliases + auto-switch) |
| Activity API | http://sparky/api/activity (nginx → :8769) |
| Shelf API | http://sparky/api/shelf/status |
| vLLM | http://sparky:8000/v1 |
| llama.cpp | http://sparky:8081/v1 |
| Open WebUI | http://sparky:3000 |
| Netdata | http://sparky:19999/v3/ |

## Rules agents should know

1. **One GPU engine at a time** — `spark engine eugr down` before `spark engine llama up` (and vice versa).
2. **Shelf APIs are unauthenticated on LAN** — OK for trusted home LAN only; don't expose port 80 WAN-side.
3. **Inventory build needs venv** — `/opt/spark/venv/bin/python scripts/spark-inventory-build.py` (HF API).
4. **Model paths** — local `/models`; optional NAS at `/mnt/model-shelf/models` when mounted.
5. **Bake-off UIs removed** — no Rookery / vLLM Studio; Phase 5 is `spark inference` + `recipes/`.
6. **Recipes are auto-scaffolded** — after download, `spark-hf` queue worker calls `scaffold_recipe` / specialized scaffolds in `spark-inference.py`. Do not hand-write recipe YAML unless scaffold cannot route the architecture (MoE, multimodal, DFlash, ds4, MTP). Extend the scaffold router in code + catalog `engine`/`capabilities` when adding new engine types. Failed scaffolds surface as `scaffold_error` on queue items — fix routing, don't bypass with manual YAML.
7. **Runtime data** (`data/inference-profiles.yaml`, `data/inference-benchmarks.yaml`) is host-local and skip-worktree — never reset from git without backup.

## `spark` CLI (humans + agents)

**Canonical reference:** `docs/reference/spark-cli.md`

Single command on PATH: **`spark`** (`install/20-spark-cli.sh`).

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
spark engine eugr status
spark engine llama status
spark gpu
```

**Agents:** use `/usr/local/bin/spark` if `PATH` is minimal; check exit codes; one GPU engine at a time.

## Install (typical order)

Orchestrator: `install/spark-install` (or `spark install …` after first `core`). See `install/INSTALL.md`.

```bash
sudo bash install/spark-install core
sudo bash install/spark-install engine eugr   # or llama / ds4 — one GPU engine at a time
sudo bash install/spark-install gateway
# Optional NAS: sudo bash install/spark-install nas
```

Legacy numbered scripts (`install/03-….sh`) still work; prefer the orchestrator.

## Inference API reload (agents)

`scripts/spark-inference-api.py` is a thin HTTP shell on **:8767** (proxied as `/api/inference/*`). It reloads `spark-inference.py` on each request — bench, switch, recipe lifecycle, and history routes all live there.

- **Routine changes to `spark-inference.py`:** no restart needed.
- **Changes to `spark-inference-api.py` itself:** `sudo bash install/spark-install restart inference-api` (or `install/19-inference-api-restart.sh`)
- **Auto-restart on script save:** chained from `spark-install core` via `install/18-inference-api-watch.sh`

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

- Text-only MM checkpoint: `--language-model-only` when `config.json` has `"language_model_only": true`.
- Grok `tool_choice: auto`: `--enable-auto-tool-choice` + `--tool-call-parser qwen3_xml` on eugr YAML.

## Chatbots in front of the gateway (optional)

SparkBench exposes an OpenAI-compatible gateway on `:9000`. Any UI/bot that speaks that protocol (Open WebUI, Hermes, LibreChat, your own client) can sit in front of it. See `services/spark-bot/README.md` for setup options — none are required.

## Threat model (short)

- LAN-trusted homelab; mutation APIs on :80 have no auth.
- Secrets: `/etc/spark/smb-credentials-models`, `HF_TOKEN` in env — never commit.

---

## Implementation notes

### Portal shared inventory module (TASK-007)

`portal/assets/spark-inventory-grid.js` exposes `window.SparkInventoryGrid` — a reusable UX primitive library for inventory-style portal pages. Loaded in `portal/index.html` with `<script defer>`.

API: `renderSummary(el, {filtered, total, suffix})`, `compareValues(a, b, col, dir)`, `renderTable(container, opts)`, `renderChips(container, chips, active, onToggle)`, `toggleGrouped(wrapEl, flat, grouped, onRender)`.

Consumed by TASK-002 (Models — done) and TASK-005 (Inference — done; uses `renderSummary` for the count line; grid rows rendered inline like Models — sort uses local `compareInfValues()` in `index.html`, not `SparkInventoryGrid.compareValues`). TASK-004 (Explore Shortlist) is done and uses `SparkInventoryGrid.compareValues` for sort. See the module header comment for integration examples.

### Client activity (TASK-001)

Pipeline: Gateway (`:9000`, `spark-inference-gateway.py`) appends JSONL to `run/inference-activity.jsonl` → Activity API (`:8769`, `spark-client-activity.py`) reads JSONL → nginx proxies `/api/activity` → Portal System tab widget.

- `json.dumps(session, separators=(",", ":"))` used in gateway to minimize JSONL line size
- Gateway `run/inference-activity.jsonl` is git-ignored; events survive gateway restarts
- Activity API is LAN-only, no auth; `install/24-client-activity-api.sh` handles systemd + nginx
- Nginx config is centralized in `install/common.sh` `write_nginx_portal_site`; add new locations there, not via sed

### Explore Shortlist / Compare view (TASK-004)

`portal/index.html` Explore card now has three sub-nav tabs persisted in `localStorage` key `sparky-explore-tab`: **Browse** (original browse + detail flow), **Shortlist** (compare table), **Downloads** (download queue full-width).

Shortlist state: `expShortlistItems` (from `data.queue.explore`), `expShortlistSelected` (Set of ids), `expShortlistSort` (`{col, dir}`).

Status enrichment: `queue_list()` in `spark-hf.py` derives `status` per explore item: `downloading > download_queued > gated > on_disk > saved`. Matched by `(repo, inventory_path)`.

Snapshot: sent client→server at save time in the POST body `snapshot: {format, engine, size_bytes, size_human, spark_fit, spark_fit_label, badges, dest}`. Server stores it on the explore queue item.

Dedupe key: `(repo, intent, inventory_path)` — stable across HF API response drift. Deduped items preserve the same `id` so UI selections survive re-saves.

Legacy items (no snapshot): enriched client-side on first Shortlist open, capped at 10 concurrent fetches via `expEnrichShortlistItems()`.

Shortlist detail drawer (`#exp-shortlist-drawer`): separate state (`expSlVariants`, `expSlSelectedVariantId`) from browse detail (`expVariants`, `expSelectedVariantId`) — no state corruption on tab switch.
