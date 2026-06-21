# Inference recipes (Phase 5)

YAML profiles for `spark-inference` (not implemented yet). Until then, use env overrides:

```bash
export SPARK_LLAMA_MODEL="$(yq -r .model gemma4-12b-coder-q4.yaml)"
export SPARK_LLAMA_NAME="$(yq -r .served_name gemma4-12b-coder-q4.yaml)"
spark-llama up
```

One GPU workload at a time — `spark-eugr down` before llama, and vice versa.
