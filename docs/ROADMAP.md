# Spark setup roadmap

**This is the plan.** Status, phases, URLs, and what to build next.  
Last updated: 2026-06-25 (vision, agent loop, reprioritized backlog)

---

## Vision

**Sparky is the Model Lab control panel for one DGX Spark:** discover models, define recipes, bench on real hardware, promote to production, and see who’s using inference — all without leaving the portal.

---

## Why this exists

Homelab control plane for **sparky** (`192.168.0.101`, DGX Spark / GB10):

| Use case | Tool |
|----------|------|
| Local agents (Hermes) — grunt work, light coding | Hermes Agent → local `:v1` endpoint |
| Private human chat | Open WebUI `:3000` |
| OSS gateway — routing, guardrails, “free” local tier | Your gateway product (separate repo) → spark backends |

**Not on sparky:** LiteLLM (gateway product already covers routing). Orchestrator UIs (Rookery, vLLM Studio) were tried and removed.

---

## Architecture (target)

```text
Hermes agents │ Open WebUI │ Your gateway
        │ many model IDs
        ▼
spark inference (Phase 5)       status + switch API
        │ one GPU profile at a time
        ▼
spark engine eugr (:8000)  │  spark engine llama (:8081)  │  spark engine ds4 (:8000)
        ▼
/opt/spark portal + inventory + recipes/
```

**Rule:** One heavy GPU workload at a time. Many logical model names; switching = evict + load (minutes for big NVFP4).

---

## Model Lab loop

The product is a **closed loop** from discovery to production. Phases 5b–5d built the backend; the backlog finishes the **operator surface** so each step is scannable in the portal.

```text
  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
  │   Explore   │────▶│   Download   │────▶│ Draft recipe    │
  │  (HF browse │     │  (HF queue → │     │ (auto-scaffold) │
  │  + shortlist)│     │   /models/)  │     │                 │
  └─────────────┘     └──────────────┘     └────────┬────────┘
                                                     │
  ┌─────────────┐     ┌──────────────┐              ▼
  │  Promote to │◀────│ Bench + test │◀────┌─────────────────┐
  │ production  │     │ (agent tok/s)│     │ Mark testing +  │
  └─────────────┘     └──────────────┘     │ switch profile  │
         │                    ▲             └────────┬────────┘
         │                    │                      │
         └────────────────────┴──────────────────────┘
                           Models inventory
                    (sizes, ctx, recipes, verify)

  Operate: gateway :9000 ← Hermes │ Open WebUI │ agents
            System tab ← client activity (TASK-001)
            Inference tab ← switch, ctx picker, logs
```

| Step | Portal | Backend |
|------|--------|---------|
| Discover | Explore tab | `/api/hf/*`, explore queue |
| Acquire | Download queue | `spark-hf`, `/models/{lab}/` |
| Define | Models → scaffold | `scaffold_auto`, `recipes/drafts/` |
| Validate | Inference → switch + bench | `spark inference`, async bench |
| Promote | Models → promote | `recipes/` + `inference-profiles.yaml` |
| Operate | System + Inference + gateway | engines, `:9000/v1` |

Future polish (post-backlog): cross-tab status chips (explore row → “draft on disk”, models → “open in Inference”) — not separate phases; small links once table/pane UX lands.

---

## Current state (today)

| Layer | Status |
|-------|--------|
| Portal, Netdata, GPU widget, inventory | ✅ Running |
| NAS shelf mount + push/pull | ✅ |
| eugr vLLM (`spark engine eugr`) | ✅ Proven |
| llama.cpp (`spark engine llama`) | ✅ Proven |
| Open WebUI | ✅ `:3000` |
| OpenCode agent profiles | ✅ `opencode-qwen36-250k` (256k MoE) · `opencode-qwen27-dflash-262k` (262k DFlash) |
| Recipes (production) | 🟡 `gemma4`, `qwen36-q4`, `qwen36-nvfp4`, `antirez-deepseek-v4-flash-ds4`, `opencode-qwen36-250k`, `opencode-qwen27-dflash-262k` (+ many testing drafts) |
| `spark inference` control plane | ✅ CLI + API + portal Inference tab + async bench |
| Model Lab (recipe lifecycle) | ✅ Phase 5b — scaffold, test, promote |
| HF Explorer | ✅ Phase 5c — Explore tab, search/trending, download queue |
| Inference API perf (lite status, YAML cache) | ✅ 2026-06-22 — models page no longer hangs on poll |
| eugr stack upgrade notice | ✅ `spark engine eugr check` + portal banner (manual upgrade) |
| DwarfStar / ds4 engine | ✅ `spark engine ds4` — antirez V4 Flash benched **17.3 tok/s** |
| MTP (Multi-Token Prediction) | ✅ Scaffold + runners; production MTP recipes bench-validated |
| Hermes Agent | ✅ Portal nav → `:9119` (iframe + online dot via `/api/gpu`) |
| Gateway integration | ✅ `spark-inference-gateway` on :9000/v1 (forward + ALIASES + auto-switch + streaming) |
| Portal UI perf/reliability | ✅ 2026-06-25 — poll guards, backoff, render diffs, nebula sqrt fix |

---

## Phase 1 — Visibility ✅

- [x] SSH, hostname `sparky`, LAN `192.168.0.101`
- [x] Portal http://sparky/ (System · Models · Explore · Inference · Hermes · Chat · Netdata)
- [x] Optional Theme B nebula (constellation toggle)
- [x] Netdata http://sparky:19999
- [x] GPU metrics http://sparky/api/gpu

---

## Phase 2 — Model shelf ✅

- [x] SMB mount `/mnt/model-shelf` (QNAP `192.168.0.99`)
- [x] Canonical tree `/models` (mirrors shelf)
- [x] `spark shelf push` / `spark shelf pull`
- [x] Inventory dashboard http://sparky/models.html
- [x] Auto-refresh (`spark models inventory` + inotify)
- [x] First full shelf push (background)
- [x] `spark hf login` for Hugging Face

LRU cache at `/var/lib/spark-model-cache` — not needed with 4 TB local NVMe.

---

## Phase 3 — Inference engines ✅

### 3a — eugr vLLM (NVFP4) ✅

Runbook: [`runbooks/smoke-vllm-eugr.md`](runbooks/smoke-vllm-eugr.md)

### 3b — llama.cpp (GGUF) ✅

Runbook: [`runbooks/smoke-llamacpp.md`](runbooks/smoke-llamacpp.md)

### 3c — DwarfStar / ds4 (DeepSeek V4 Flash) ✅

**Goal:** Third inference engine for native DeepSeek V4 Flash (antirez [ds4](https://github.com/antirez/ds4)), OpenAI `/v1`, separate from eugr vLLM and llama.cpp.

| Item | Status |
|------|--------|
| Pin file | [`data/ds4-dwarfstar.yaml`](../data/ds4-dwarfstar.yaml) — Entrpi `decode-perf-tuning` @ `5625a99d` |
| Install | [`install/22-ds4-dwarfstar.sh`](../install/22-ds4-dwarfstar.sh) (~2 min rebuild) |
| Runbook | [`runbooks/smoke-ds4.md`](runbooks/smoke-ds4.md) |
| Control plane | ✅ `spark engine ds4`, `engine: ds4` recipes, inference switch, portal badges |
| Production recipe | ✅ `antirez-deepseek-v4-flash-ds4` — **17.3 tok/s** (bench-agent, thinking disabled) |
| 0xSero REAP GGUF | Stays on **llama.cpp** (`0xsero/deepseek-v4-flash-spark`) — not ds4 |

**Note:** Pin YAML + table above remain source of truth. Bench worker uses `thinking: {type: disabled}` for ds4 (thinking mode can CUDA-fault on long agent-style benches).


---

## Phase 4 — Orchestrator UI bake-off ✅ closed

**Keep:** Open WebUI for chat only. Phase 5 thin control plane wins.

---

## Phase 5 — Inference runtime ✅ (core)

**Goal:** Recipe-defined profiles, unified switch CLI/API, portal status panel.

Spec: [`reference/inference-stack.md`](reference/inference-stack.md)

### 5.0 — Runtime control plane ✅

1. [x] Expand `recipes/` — Qwen NVFP4, Qwen Q4, Gemma Q4
2. [x] **`spark inference`** CLI — `status`, `list`, `up`, `down`, `logs`, `bench`
3. [x] **HTTP API** — status, switch, down, bench (async background job)
4. [x] **Portal Inference tab** — switch, stop, benchmark, log tail
5. [x] **Portal UX** — nav order, unified pills, Models↔Inference bridge
6. [x] **Benchmarks** — multi-turn agent bench, recipe-level tok/s, speed sort
7. [x] **API auto-reload** — `install/18-inference-api-watch.sh` (systemd path unit)
8. [x] **Status API perf** — YAML mtime caches, 1s TTL snapshot, `?lite=1` for nav/models polls, `ThreadingHTTPServer` (`2026-06-22`)
9. [x] **eugr upgrade detection** — `spark engine eugr check` / `record`, portal banner, runbook [`eugr-vllm-upgrade.md`](runbooks/eugr-vllm-upgrade.md)
10. [x] **Gateway integration** — `spark-inference-gateway` on :9000/v1 (forward + ALIASES + auto-switch + streaming) — smallest useful slice implemented
11. [x] **OpenCode profiles** — 35B MoE @ 256k + 27B DFlash @ 262k for long-context agents
12. [x] **Hermes Agent** — portal nav embeds local Hermes dashboard (`:9119`); status dot from `/api/gpu`

---

## Phase 5b — Model Lab: recipe lifecycle ✅

**Goal:** Model → draft recipe → test → bench → promote.

Benchmarks are **per recipe** (profile), not per model weights — same `inventory_path` can have multiple recipes (NVFP4 eugr vs Q4 llama).

**How recipes are created (default path):** Humans rarely hand-write YAML. After a download completes, the **auto-scaffold loop** (`spark-hf` queue worker → `scaffold_recipe` / specialized scaffolds in `spark-inference.py`) should pick engine, tier, and recipe shape from **weights on disk + HF metadata** (format, architecture, catalog `engine` / capabilities). Agents follow the same routing — do not invent recipes when scaffold can derive them. When architecture or engine requirements differ (MoE, multimodal, DFlash sidecar, ds4, MTP), extend the **scaffold router** and document the rule in catalog/AGENT.md — not one-off YAML.

### Build order (5b → 5c → 5d)

1. [x] `recipes/drafts/` + `lifecycle` field (`draft` → `testing` → `production`)
2. [x] **`spark recipe`** — `scaffold`, `list`, `promote`, `discard`, `testing`
3. [x] **HTTP API** — `GET/POST /api/inference/recipes/*`
4. [x] **Portal Models** — Create recipe, mark testing, switch, bench, promote
5. [x] Testing recipes switchable; production = `data/inference-profiles.yaml`

**Ops:** API hot-reloads `spark-inference.py` on request (no restart for most changes). One-time: `install/18` (watch) or `install/19` (manual restart); agents use `sudo bash install/19-inference-api-restart.sh` if needed.

### States

| State | Location | Switchable | In production index |
|-------|----------|------------|---------------------|
| `draft` | `recipes/drafts/` | No | No |
| `testing` | `recipes/drafts/` | Yes | No |
| `production` | `recipes/` | Yes | Yes |

---

## Phase 5c — HF Explorer ✅

**Goal:** Own HF discovery inside the portal — search, trending, download.

1. [x] `GET /api/hf/search`, `/trending`, `/new`, `/model/{id}`, `/queue` — `spark-hf-api` (`install/21-hf-api.sh`)
2. [x] Portal **Explore** tab — search, mode chips (trending/new), format/architecture filters
3. [x] `POST /api/hf/queue` — background download → `/models/{lab}/{slug}/`
4. [x] On complete → merge catalog + auto-scaffold draft recipe (eugr/llama today)

**Scaffold router (grow as engines/features land):**

| Signal | Scaffold path |
|--------|----------------|
| GGUF on disk | `llamacpp` (`scaffold_recipe`) |
| nvfp4 / hf / fp8 weights | `eugr` (`scaffold_recipe` + `config.json` heuristics) |
| DFlash sidecar repo | `scaffold_dflash_recipe` (pair with target; NVFP4 MoE guard) |
| `engine: ds4` in catalog | `scaffold_ds4_recipe()` — pinned to `antirez/deepseek-v4-flash` |
| MTP / speculative (5d) | `scaffold_auto` → `mtp_eugr` / `mtp_llama` / `dflash` |

---

## Phase 5d — Scaffold router: MTP, speculative, odd architectures ✅ (control plane)

**Goal:** Extend **auto-scaffold** (not hand-written recipes) so download-complete and agent-driven flows detect architecture/requirements and emit the right draft recipe + engine flags.

1. [x] Central **scaffold dispatch** — `resolve_scaffold_kind` + `scaffold_auto()` (plan + on-disk layout → `llamacpp` | `eugr` | `ds4` | `dflash` | `mtp_eugr` | `mtp_llama`)
2. [x] Recipe `speculative:` / `mtp:` blocks generated by scaffold (`scaffold_dflash_recipe`, `scaffold_mtp_eugr_recipe`, `scaffold_mtp_llamacpp_recipe`)
3. [x] Qwen3.6 MTP — auto-scaffold when MTP GGUF pair or `mtp.safetensors` beside eugr weights detected
4. [x] Gemma / generic MTP GGUF — llama.cpp draft model path in scaffold output (`mtp.draft_model`)
5. [x] DFlash — `scaffold_dflash_recipe` wired through HF queue (`scaffold_kind`) + `POST /api/inference/recipes/scaffold` auto path
6. [x] Side-by-side bench in Model Lab UI — `renderBenchCompareStrip` on Models page; DFlash/MTP badges on Models + Inference tabs
7. [x] **llama.cpp + eugr MTP runners** — scaffold emits recipes; MTP profiles switch and pass agent bench

**Agent rule:** If scaffold fails (`scaffold_error` on queue item), fix routing or add a scaffold branch — do not paste a recipe YAML unless the architecture is genuinely one-off.

---

## Backlog (next features)

**Agent workflow:** [`roadmap/README.md`](roadmap/README.md) — work on **techno**, **one PR per task**, merge **in sequence**, then deploy to sparky for smoke.

| Seq | Task | Status | One PR | Doc |
|-----|------|--------|--------|-----|
| 1 | Portal foundation — CSS extract, defer scripts, models poll fixes | ready | yes | [TASK-006](roadmap/tasks/TASK-006-portal-foundation.md) |
| 2 | Shared inventory grid module | done | yes | [TASK-007](roadmap/tasks/TASK-007-shared-inventory-grid.md) |
| 3 | Client activity dashboard (System tab) | done | yes | [TASK-001](roadmap/tasks/TASK-001-client-activity-dashboard.md) |
| 4 | Models inventory UX — sortable table + detail side pane | done | yes | [TASK-002](roadmap/tasks/TASK-002-models-inventory-ux.md) |
| 5 | Inference page — flat recipe grid, ctx labeling | done | yes | [TASK-005](roadmap/tasks/TASK-005-inference-page-ux.md) |
| 6 | Explore queue — shortlist compare overhaul | ready | yes | [TASK-004](roadmap/tasks/TASK-004-explore-queue-overhaul.md) |

**How to run one main agent:** point it at `docs/ROADMAP.md` + `docs/roadmap/README.md`. It picks **Seq 1**, implements the full task file, opens **one PR** to `origin`, stops. After you review/merge and deploy, it picks **Seq 2**, and so on. No parallel PRs; no splitting a task across PRs.

**Superseded:** old split Models tasks → single [TASK-002-models-inventory-ux.md](roadmap/tasks/TASK-002-models-inventory-ux.md).

---

## UI polish (remaining)

Most Opus items shipped 2026-06-25 ([`reference/ui-improvements-opus.md`](reference/ui-improvements-opus.md)). **Seq 1 (TASK-006)** owns the rest: CSS extract, defer, models poll. Optional AbortController on view switch can ride along or stay deferred.

---

## Quick reference

CLI guide (humans + agents): [`reference/spark-cli.md`](reference/spark-cli.md)

| Service | URL | Command |
|---------|-----|---------|
| Portal | http://sparky/ | nginx |
| Models | http://sparky/models.html | `spark models inventory` |
| Inference API | http://sparky/api/inference/status | `spark inference status` |
| Inference API (lite) | http://sparky/api/inference/status?lite=1 | nav/models polls only |
| Activity API | http://sparky/api/activity | System-tab client activity widget |
| HF Explorer API | http://sparky/api/hf/status | Explore tab |
| vLLM | http://sparky:8000/v1 | `spark engine eugr up/down/status` |
| eugr stack check | — | `spark engine eugr check` |
| llama.cpp | http://sparky:8081/v1 | `spark engine llama up/down/status` |
| DwarfStar | http://sparky:8000/v1 | `spark engine ds4 up/down/status` |
| Hermes Agent | http://sparky:9119/ | docker (`spark-bot`) |
| Open WebUI | http://sparky:3000 | docker |
| Netdata | http://sparky:19999/v3/ | — |
| Shelf | — | `spark shelf push`, `spark shelf pull` |

---

## Repo layout

```
/opt/spark/
├── AGENT.md
├── portal/
├── scripts/           spark CLI + implementation scripts
├── install/
├── data/              catalog, verification, inference-profiles.yaml, ds4-dwarfstar.yaml (pin)
├── recipes/           production inference profiles
│   └── drafts/        Model Lab draft/testing recipes (Phase 5b)
├── docs/
└── services/          eugr per-model launch yaml
```

Staging: `~/spark` → promoted by install scripts.

---

## Documentation

See [`README.md`](../README.md) for the doc index and repo homepage.