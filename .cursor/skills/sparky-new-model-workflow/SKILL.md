---
name: sparky-new-model-workflow
description: >-
  Full golden workflow on Sparky homelab: golden bench v2, KV sweep, ctx ladder,
  verify works, inventory rebuild. Use when user says "golden workflow", "golden audit",
  onboarding models to /models, or benchmarking new downloads.
---

# Sparky golden workflow

Production host: **`sparky`**, repo **`/opt/spark`**.

**When the user says "do the golden workflow on a model"** → run `spark-golden-workflow.py` for that inventory path (or `spark models golden <lab/slug>`).

## Policy

- **`works` only after golden phase bench v2 succeeds** — never from load-only smoke.
- **One golden profile** per `inventory_path` in `data/golden-recipes.yaml`.
- **Bench standard v2** for the golden cell; kv sweep + ctx ladder use **lite v2** (one session, 75% ctx fill).
- **Skip shelf by default** (`--skip-shelf`) unless user asks — large rsyncs block for hours.
- **0xsero/deepseek-v4-flash-spark** — skipped (REAP GGUF load fails).

## Layers (sequential, GPU-bound)

| Layer | Script | What it measures |
|-------|--------|------------------|
| 1. Golden | `golden-inventory-audit.py` | Optimize ctx/kv, full bench v2, promote, `works` |
| 2. KV sweep | `spark-kv-sweep.py` | Golden ctx × engine KV quants @ 75% fill → tok/s |
| 3. Ctx ladder | `spark-ctx-ladder.py` | Golden kv × ctx rungs to native @ 75% fill → tok/s |
| 4. Shelf | `spark shelf push` | Optional NAS backup |

Results persist on the recipe as `context.bench_matrix` (+ `kv_sweep`, `ctx_ladder`).

## Quick path (one model)

```bash
# Register golden in data/golden-recipes.yaml + DEFAULT_GOLDEN if needed
spark recipe scaffold <lab>/<slug> eugr   # or llamacpp

# Full workflow (hours possible for long-ctx models)
spark models golden <lab>/<slug>

# Or background
nohup /opt/spark/venv/bin/python3 /opt/spark/scripts/spark-golden-workflow.py \
  --only "<lab>/<slug>" --skip-shelf --resume \
  >> /opt/spark/logs/golden-workflow.log 2>&1 &
```

## Fleet (all golden models)

```bash
nohup /opt/spark/venv/bin/python3 /opt/spark/scripts/spark-golden-workflow.py \
  --all --skip-shelf --resume \
  >> /opt/spark/logs/golden-workflow.log 2>&1 &
```

`--resume` skips phases already `ok` in `/opt/spark/run/golden-workflow-report.json`.

## Monitor

```bash
tail -f /opt/spark/logs/golden-workflow.log
cat /opt/spark/run/golden-workflow-report.json | python3 -m json.tool
```

## Wrapper script

```bash
/opt/spark/scripts/spark-new-model-golden.sh qwen/qwen-agentworld-35b-a3b
```

## Status meanings

| Workflow status | Meaning |
|-----------------|---------|
| `complete` | Golden + kv sweep + ctx ladder (+ shelf if requested) all ok/skipped |
| `partial` | Golden ok; later layer failed |
| `failed` | Golden phase failed |

## Reference

- `docs/runbooks/new-model-golden-benchmark.md`
- `docs/reference/benchmark-standard.md`
- `scripts/spark-golden-workflow.py` — orchestrator
- `scripts/spark-golden-bench.py` — shared 75% fill probes
