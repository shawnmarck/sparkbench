# Contributing

SparkBench is the tool you run on your own DGX Spark. The public site at [sparkbench.dev](https://sparkbench.dev) is generated separately from this repo's data — contributions to benchmarks and recipes show up there automatically.

## Setup

Clone the repo and deploy to your Spark machine:

```bash
git clone https://github.com/shawnmarck/sparkbench
cd sparkbench
./scripts/deploy-sparky.sh
```

Set `SPARK_HOST` (default `sparky`) and `SPARK_LAN_IP` (default from `install/common.sh`) to match your machine if they differ.

## Workflow

- One PR per task — keep diffs focused and reviewable
- After merging, run a deploy smoke: `./scripts/deploy-sparky.sh && ./scripts/deploy-sparky.sh --status`
- All install scripts are idempotent — safe to re-run

## Adding a recipe

1. Add an entry to `data/golden-recipes.yaml` following the existing schema
2. Optionally add a standalone file under `recipes/`
3. Run the benchmark harness locally to fill in `tok_s` and `ctx` fields before opening a PR

## Adding a published SWE / Terminal-Bench score

sparkbench.dev can show **vendor-published** agentic scores next to GB10 tok/s. These are not measured on Sparky.

1. Edit [`data/published-evals.yaml`](data/published-evals.yaml)
2. Put numbers on the **canonical base** (e.g. `qwen/qwen3.6-35b-a3b`), not a quant pack
3. Every score needs `source_url` and `as_of`
4. List same-weight packs under `aliases`; do not alias finetunes
5. Optional `aa_url` is a link to Artificial Analysis — do not copy AA scores

See [`docs/reference/published-evals.md`](docs/reference/published-evals.md).

## Pull request checklist

- [ ] No hardcoded LAN IPs or private hostnames in docs or scripts (use `$SPARK_HOST` / `$SPARK_LAN_IP`)
- [ ] Install scripts pass an idempotent re-run without errors
- [ ] Deploy smoke passes on a real Spark after merge

## Not affiliated

This project is not affiliated with or endorsed by NVIDIA Corporation.
