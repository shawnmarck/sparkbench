---
name: sparkbench
description: >-
  Install and operate SparkBench on a DGX Spark (GB10): spark CLI, HTTP control APIs,
  and portal UI. Use when the user mentions SparkBench, sparky, spark inference,
  model lab, golden audit, spark-install, /models, HF explore queue, gateway :9000,
  or running benchmarks on a Spark box — including remote SSH or HTTP-only harnesses.
---

# SparkBench

Follow **`docs/guides/installation-instructions.md`** step by step.

If the repo is not on disk yet, fetch the guide:

```bash
curl -fsSL https://raw.githubusercontent.com/shawnmarck/sparkbench/v0.1.0/docs/guides/installation-instructions.md
```

Execute every step in order. Three surfaces: **CLI** (`spark`), **HTTP** (`/api/…`), **Portal** (`http://$SPARK_HOST/`).

For HTTP route tables when working inside a clone, see [references/api.md](references/api.md).
