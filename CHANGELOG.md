# Changelog

All notable changes to SparkBench are documented here. Versioning follows [SemVer](https://semver.org/).

## [0.1.0] — 2026-06-27

First public release. SparkBench is a self-hosted model lab for the NVIDIA DGX Spark (GB10): portal UI, inference control plane, benchmark harness, and optional NAS shelf sync.

### Install

- **`spark-install` orchestrator** — single entry point: `sudo bash install/spark-install <target>`
- **Targets:** `bootstrap`, `core`, `nas`, `engine eugr|llama|ds4`, `gateway`, `openwebui`, `module …`, `extras …`, `status`
- **Purpose-named modules** under `install/modules/` (core, engines, gateway, bootstrap, optional, extras)
- **Nginx batching** during `core` and `gateway` runs — one portal site rewrite at the end
- **Host identity:** `install/host.env.example` → `/etc/spark/host.env` or `$SPARK_ROOT/host.env`
- **Runtime protection:** `scripts/sparky-protect-runtime.sh` (skip-worktree on host-local inference YAML)
- **`spark install …`** — same orchestrator via the unified CLI after `core`

### Portal (nginx :80)

- System tab — GPU metrics, client activity, service links
- **Models** — catalog grid, verification tags, Model Lab detail
- **Inference** — profile switch, bench trigger, engine status
- **Explore** — HuggingFace browse, shortlist compare, download queue

### `spark` CLI

- One binary on PATH: `spark status`, `spark inference …`, `spark recipe …`, `spark models …`, `spark hf …`, `spark shelf …`, `spark engine …`, `spark gpu`
- Designed for humans and coding agents; full reference in `docs/reference/spark-cli.md`

### Inference engines (one GPU at a time)

- **eugr** — vLLM NVFP4 / FP8 (`:8000`)
- **llama.cpp** — GGUF (`:8081`)
- **ds4** — DwarfStar DeepSeek V4 Flash (`:8000`, mutually exclusive with eugr)
- **Recipes** in `recipes/` — draft → testing → production lifecycle
- **Auto-scaffold** from weights + catalog after HF download
- **Golden map** in `data/golden-recipes.yaml` for production profiles

### Benchmarks

- **Bench v2** standard — long context, tools, agent turns (`docs/reference/benchmark-standard.md`)
- `spark inference bench` — tok/s on the active profile
- Results feed portal cards and [sparkbench.dev](https://sparkbench.dev) leaderboard data
- **`works` verification** gated on successful bench v2

### HuggingFace & models

- Explore API + download queue (`spark hf`, portal Explore tab)
- Canonical weight tree at `/models/{lab}/{slug}/`
- **Optional NAS shelf** — CIFS mount + `spark shelf pull|push` when configured
- Inventory builder → `portal/models.json` (`spark models inventory`)

### Gateway & APIs

- **OpenAI-compatible gateway** — `http://<host>:9000/v1` (aliases + auto-switch)
- **Control API** — `/api/inference/*` (switch, bench, recipes)
- **Shelf / GPU / HF / activity** — `/api/shelf/*`, `/api/gpu`, `/api/hf/*`, `/api/activity`
- LAN-trusted homelab model — no auth on mutation APIs

### LLM agents

- **`docs/guides/installation-instructions.md`** — step-by-step install and ops guide (fetch via README Quickstart)
- **Project skill** — `.claude/skills/sparkbench/` (Claude Code `/sparkbench`)
- **`spark-install extras agent-skill`** — copy skill to `~/.claude/skills` and `~/.cursor/skills`
- **`AGENTS.md`** — repo layout, rules, and code touchpoints

### Documentation

- Runbooks: smoke tests (eugr, llama, ds4), golden audit, live sync on sparky
- Guides: first Spark setup, model shelf, local model testing, model picks
- Reference: inference stack, spark CLI, benchmark standard

[0.1.0]: https://github.com/shawnmarck/sparkbench/releases/tag/v0.1.0
