# Spark setup roadmap

**This is the plan.** Status, phases, URLs, and what to build next.  
Last updated: 2026-06-21

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
spark engine eugr (:8000)  │  spark engine llama (:8081)
        ▼
/opt/spark portal + inventory + recipes/
```

**Rule:** One heavy GPU workload at a time. Many logical model names; switching = evict + load (minutes for big NVFP4).

**Model Lab arc (Phase 5b–5d):** Explore (HF) → Download → Draft recipe → Test/bench → Promote to production.

---

## Current state (today)

| Layer | Status |
|-------|--------|
| Portal, Netdata, GPU widget, inventory | ✅ Running |
| NAS shelf mount + push/pull | ✅ |
| eugr vLLM (`spark engine eugr`) | ✅ Proven |
| llama.cpp (`spark engine llama`) | ✅ Proven |
| Open WebUI | ✅ `:3000` |
| Recipes (production) | 🟡 `gemma4`, `qwen36-q4`, `qwen36-nvfp4` |
| `spark inference` control plane | 🟡 CLI + API + portal Inference tab + async bench |
| Model Lab (recipe lifecycle) | ✅ Phase 5b — scaffold, test, promote |
| HF Explorer | ❌ Phase 5c |
| Hermes Agent | ❌ Phase 5 step 5 (deferred) |
| Gateway integration | ❌ Phase 5 step 6 |

---

## Phase 1 — Visibility ✅

- [x] SSH, hostname `sparky`, LAN `192.168.0.101`
- [x] Portal http://sparky/ (System · Models · Inference · Chat · Netdata)
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
- [ ] Second shelf push for Gemma 4 trees (after downloads)

Deferred: LRU cache at `/var/lib/spark-model-cache` — not needed with 4 TB local NVMe.

---

## Phase 3 — Inference engines ✅

### 3a — eugr vLLM (NVFP4) ✅

Runbook: [`runbooks/smoke-vllm-eugr.md`](runbooks/smoke-vllm-eugr.md)

### 3b — llama.cpp (GGUF) ✅

Runbook: [`runbooks/smoke-llamacpp.md`](runbooks/smoke-llamacpp.md)

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
8. [ ] **Hermes Agent** — install, point at fast local tier (deferred)
9. [ ] **Gateway integration** — model aliases → profiles, cold-start 503/retry
10. [ ] Later: idle eviction, MCP ops agent

---

## Phase 5b — Model Lab: recipe lifecycle ✅

**Goal:** Model → draft recipe → test → bench → promote. No HF UI yet.

Benchmarks are **per recipe** (profile), not per model weights — same `inventory_path` can have multiple recipes (NVFP4 eugr vs Q4 llama).

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

## Phase 5c — HF Explorer 🔜 (next)

**Goal:** Own HF discovery inside the portal — search, trending, download.

1. [ ] `GET /api/hf/search`, `/trending`, `/model/{id}` (Hub API + cache)
2. [ ] Portal **Explore** tab — search, filters (GGUF, NVFP4, MoE)
3. [ ] `POST /api/hf/download` — background job → `/models/{lab}/{slug}/`
4. [ ] On complete → add to catalog + scaffold draft recipe

---

## Phase 5d — Experimental recipes (MTP, speculative) ⏳

**Goal:** Recipe passthrough for eugr/llama flags; bench compare A vs B.

1. [ ] Recipe `speculative:` block (engine-specific)
2. [ ] `qwen36-nvfp4-mtp` eugr profile (vendor recipe already supports MTP)
3. [ ] Gemma MTP via llama.cpp draft model in recipe
4. [ ] Side-by-side bench in Model Lab UI

---

## Phase 6 — Closet / 10Gb ⏸

Deferred until desk setup is stable.

---

## Deferred / later

- Tailscale remote access
- Portal TPS / vLLM `/metrics` scrape
- Netdata vLLM integration
- Always-on small + on-demand heavy (only if VRAM headroom proven)

---

## Quick reference

| Service | URL | Command |
|---------|-----|---------|
| Portal | http://sparky/ | nginx |
| Models | http://sparky/models.html | `spark models inventory` |
| Inference API | http://sparky/api/inference/status | `spark inference status` |
| vLLM | http://sparky:8000/v1 | `spark engine eugr up/down/status` |
| llama.cpp | http://sparky:8081/v1 | `spark engine llama up/down/status` |
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
├── data/              catalog, verification, inference-profiles.yaml
├── recipes/           production inference profiles
│   └── drafts/        Model Lab draft/testing recipes (Phase 5b)
├── docs/
└── services/          eugr per-model launch yaml
```

Staging: `~/spark` → promoted by install scripts.

---

## Documentation

See [`README.md`](../README.md) for the doc index and repo homepage.