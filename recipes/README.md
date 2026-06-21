# Inference recipes (Phase 5)

YAML profiles for `spark-inference`. One GPU workload at a time.

```bash
spark-inference list
spark-inference status
spark-inference up gemma4-12b-coder-q4
spark-inference down
spark-inference logs
```

Enable/disable profiles in `data/inference-profiles.yaml`. Until `spark-inference` is installed to `/usr/local/bin`, run via `/opt/spark/scripts/spark-inference`.

Direct engine control still works:

```bash
spark-eugr down && spark-llama up    # or the reverse
```

Recipe env overrides (used by `spark-inference up`):

```bash
SPARK_LLAMA_RECIPE=/opt/spark/recipes/gemma4-12b-coder-q4.yaml spark-llama up
SPARK_EUGR_RECIPE=/opt/spark/services/eugr-qwen36-local.yaml spark-eugr up
```