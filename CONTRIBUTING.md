# Contributing

## Setup

Clone the repo and deploy to your Spark machine:

```bash
git clone https://github.com/shawnmarck/sparky-dashboard
cd sparky-dashboard
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

## Pull request checklist

- [ ] No hardcoded LAN IPs or private hostnames in docs or scripts (use `$SPARK_HOST` / `$SPARK_LAN_IP`)
- [ ] Install scripts pass an idempotent re-run without errors
- [ ] Deploy smoke passes on a real Spark after merge

## Not affiliated

This project is not affiliated with or endorsed by NVIDIA Corporation.
