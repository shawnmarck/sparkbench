# Spark setup roadmap

**This is the plan.** Status, phases, URLs, and what to build next.  
Last updated: 2026-06-22 (inference gateway :9000/v1 implemented)

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
| Recipes (production) | 🟡 `gemma4`, `qwen36-q4`, `qwen36-nvfp4` (+ many testing drafts) |
| `spark inference` control plane | ✅ CLI + API + portal Inference tab + async bench |
| Model Lab (recipe lifecycle) | ✅ Phase 5b — scaffold, test, promote |
| HF Explorer | ✅ Phase 5c — Explore tab, search/trending, download queue |
| Inference API perf (lite status, YAML cache) | ✅ 2026-06-22 — models page no longer hangs on poll |
| eugr stack upgrade notice | ✅ `spark engine eugr check` + portal banner (manual upgrade) |
| DwarfStar / ds4 engine | ✅ `spark engine ds4` — antirez V4 Flash benched **17.3 tok/s** |
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
10. [ ] **Hermes Agent** — install, point at fast local tier (deferred)
11. [x] **Gateway integration** — `spark-inference-gateway` on :9000/v1 (forward + ALIASES + auto-switch + streaming) — smallest useful slice implemented
12. [ ] Later: idle eviction, MCP ops agent

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

**Next (5c polish):** Explore → Model Lab handoff UX, queue visibility on Models page.

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

**Remaining (data plane / runners, not 5d control plane):** llama.cpp MTP draft wiring in `spark-llama`; eugr MTP bench validation on hardware.

**Agent rule:** If scaffold fails (`scaffold_error` on queue item), fix routing or add a scaffold branch — do not paste a recipe YAML unless the architecture is genuinely one-off.

---

## Phase 6 — Closet / 10Gb ⏸

Deferred until desk setup is stable.

---

## Deferred / later

- **DwarfStar MTP / thinking-mode benches** — optional; default bench disables thinking
- Tailscale remote access
- Portal TPS / vLLM `/metrics` scrape
- Netdata vLLM integration
- Always-on small + on-demand heavy (only if VRAM headroom proven)
- Status cache hardening — YAML cache locks, single-flight coalesce, deepcopy on cache hit (review follow-ups)

---

## Quick reference

CLI guide (humans + agents): [`reference/spark-cli.md`](reference/spark-cli.md)

| Service | URL | Command |
|---------|-----|---------|
| Portal | http://sparky/ | nginx |
| Models | http://sparky/models.html | `spark models inventory` |
| Inference API | http://sparky/api/inference/status | `spark inference status` |
| Inference API (lite) | http://sparky/api/inference/status?lite=1 | nav/models polls only |
| HF Explorer API | http://sparky/api/hf/status | Explore tab |
| vLLM | http://sparky:8000/v1 | `spark engine eugr up/down/status` |
| eugr stack check | — | `spark engine eugr check` |
| llama.cpp | http://sparky:8081/v1 | `spark engine llama up/down/status` |
| DwarfStar | http://sparky:8000/v1 | `spark engine ds4 up/down/status` |
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