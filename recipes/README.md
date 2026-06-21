# Inference recipes (Phase 5)

YAML profiles for `spark inference`. One GPU workload at a time.

```bash
spark inference list
spark inference status
spark inference up gemma4-12b-coder-q4
spark inference down
spark inference logs
spark recipe list          # includes drafts/testing
```

Enable/disable profiles in `data/inference-profiles.yaml`. Install CLI: `sudo bash install/20-spark-cli.sh`.

Direct engine control still works:

```bash
spark engine eugr down && spark engine llama up    # or the reverse
```

Recipe env overrides (used by `spark inference up` or direct engine control):

```bash
SPARK_LLAMA_RECIPE=/opt/spark/recipes/gemma4-12b-coder-q4.yaml spark engine llama up
SPARK_EUGR_RECIPE=/opt/spark/services/eugr-qwen36-local.yaml spark engine eugr up
```