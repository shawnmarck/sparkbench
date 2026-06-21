# Documentation

**Start here:** [`ROADMAP.md`](ROADMAP.md) — phases, current state, and what to build next.

**Agents:** [`../AGENT.md`](../AGENT.md) — repo layout, rules, commands.

**Install scripts:** [`../install/INSTALL.md`](../install/INSTALL.md)

---

## How docs are organized

| Folder | Purpose |
|--------|---------|
| *(root)* | **ROADMAP.md** — the plan. **README.md** — this index. |
| [`guides/`](guides/) | Ongoing reference you’ll revisit (shelf layout, model catalog rationale) |
| [`runbooks/`](runbooks/) | Step-by-step “how we proved X works” (smoke tests) |
| [`reference/`](reference/) | Technical specs for work not yet built |
| [`examples/`](examples/) | Copy-paste YAML templates (not runtime config) |

---

## What each file is for

### ROADMAP.md
The single source of truth for **phases, status, URLs, and next steps**. If you’re asking “where are we?” or “what’s next?” — read this.

### guides/model-shelf.md
**Where models live** on disk and on the QNAP NAS: `/models` vs `/mnt/model-shelf/models`, folder naming (`lab/model-version/`), variants (`hf/`, `nvfp4/`, `gguf/`). Use when syncing, pushing to shelf, or adding a new model tree.

### guides/model-picks.md
**Why each model is in the library** — the curated download list, sizes, engines, and rationale (not a live log). Pairs with `data/model-catalog.yaml` (machine-readable) and the Models portal page. Update when you add/remove catalog entries.

### runbooks/smoke-vllm-eugr.md
**One-time / repeat validation** that eugr vLLM runs Qwen3.6 NVFP4 on GB10: build `vllm-node`, `spark-eugr up`, hit `:8000/v1`. Phase 3a checklist — not day-to-day ops (use `spark-eugr` for that).

### runbooks/smoke-llamacpp.md
**Same idea for llama.cpp** — build `llama-server`, load a GGUF, hit `:8081/v1`. Phase 3b checklist.

### reference/inference-stack.md
**Phase 5 design doc** — recipe format, `spark-inference` CLI/API, portal panel, gateway swap semantics. ROADMAP says *what* to do; this says *how* it should work. Shrinks as features land in code.

### examples/model-manifest.yaml.example
**Template for per-model metadata** under `/models/{lab}/{slug}/manifest.yaml` — documents variants (GGUF quant, HF, NVFP4), engines, license. Optional convention; not required for inference to run.

### examples/download-batch.yaml
**Human-readable manifest** of the initial bulk download batch (repos, paths, sizes). The actual downloader is `scripts/spark-download-models.sh` (hardcoded). This YAML is documentation + a record of what that script was designed to fetch — not read at runtime.

---

## What we removed

- **BAKE-OFF.md**, **OPS-LAYOUT.md** — Phase 4 orchestrator UIs (Rookery, vLLM Studio) removed from the box; no longer documented here.

---

## Changelog

- 2026-06-21: Reorganized docs into guides/ runbooks/ reference/ examples/; ROADMAP is the master plan.
