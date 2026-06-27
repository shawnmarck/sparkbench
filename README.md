# SparkBench

Run this on your **DGX Spark** (GB10) to get a portal, model inventory, inference control plane, and benchmark harness — all running locally on your hardware.

**[sparkbench.dev](https://sparkbench.dev)** — public leaderboard: model rankings, benchmark results, and what runs well on GB10.

> Not affiliated with or endorsed by NVIDIA Corporation.

<p align="center">
  <img src="docs/assets/portal-nebula-theme.gif" width="820" alt="Portal nebula theme demo — Theme B nebula background with constellation toggle">
</p>

## Links

| | |
|---|---|
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases, status, what's next |
| [AGENT.md](AGENT.md) | Repo layout, rules, agent quick-start |
| [docs/reference/spark-cli.md](docs/reference/spark-cli.md) | **spark CLI** — humans, coding agents, HTTP APIs |
| [install/INSTALL.md](install/INSTALL.md) | Install script index |

## Deploy

From your clone (after commit):

```bash
SPARK_HOST=sparky ./scripts/deploy-sparky.sh
SPARK_HOST=sparky ./scripts/deploy-sparky.sh --status   # drift check
```

Set `SPARK_HOST` to match your machine's hostname or IP.

## Docs

| Path | Topic |
|------|-------|
| [docs/guides/model-shelf.md](docs/guides/model-shelf.md) | `/models` + NAS shelf layout |
| [docs/guides/model-picks.md](docs/guides/model-picks.md) | Why each model is in the catalog |
| [docs/runbooks/smoke-vllm-eugr.md](docs/runbooks/smoke-vllm-eugr.md) | eugr vLLM smoke test |
| [docs/runbooks/smoke-llamacpp.md](docs/runbooks/smoke-llamacpp.md) | llama.cpp smoke test |
| [`docs/runbooks/smoke-ds4.md`](docs/runbooks/smoke-ds4.md) | DwarfStar ds4 smoke |
| [docs/reference/inference-stack.md](docs/reference/inference-stack.md) | Phase 5 inference control plane |
| [docs/reference/benchmark-standard.md](docs/reference/benchmark-standard.md) | Versioned bench v2 (long-ctx + tools) |
| [docs/runbooks/new-model-golden-benchmark.md](docs/runbooks/new-model-golden-benchmark.md) | New model golden audit |
| [docs/guides/local-model-testing.md](docs/guides/local-model-testing.md) | Bench queue + stack fixes SOP |
| [docs/guides/first-spark-setup.md](docs/guides/first-spark-setup.md) | **First Spark setup** — solo GB10 clone → golden recipes → fetch |
| [AGENT.md](AGENT.md) | Agent rules + **deploy workflow** (`scripts/deploy-sparky.sh`) |
| [docs/reference/spark-cli.md](docs/reference/spark-cli.md) | Unified `spark` command reference |
| [docs/examples/](docs/examples/) | YAML templates |