# Inference recipes

YAML profiles for `spark inference`. One GPU workload at a time.

```bash
spark inference list
spark inference status
spark inference up opencode-qwen36-250k
spark inference down
spark inference logs
spark recipe list          # includes drafts / testing
```

Enable or disable ids in host-local `data/inference-profiles.yaml`. Install: `sudo bash install/spark-install core`.

Direct engine control still works:

```bash
spark engine eugr down && spark engine llama up
```

Recipe env overrides (`spark inference up` or direct engine control):

```bash
SPARK_LLAMA_RECIPE=/opt/spark/recipes/qwen36-q4-llama.yaml spark engine llama up
SPARK_EUGR_RECIPE=/opt/spark/services/eugr-qwen36-local.yaml spark engine eugr up
```

Scaffold new profiles with `spark recipe scaffold <lab/slug> <engine>`. Extend the router before hand-writing YAML. See [inference-stack.md](../docs/reference/inference-stack.md).

## Agent profiles (long context)

Via `http://sparky:9000/v1`, model `sparky`:

| Profile | Model | Notes |
|---------|-------|-------|
| `opencode-qwen36-250k` | Qwen3.6-35B-A3B NVFP4 | 256k, everyday coding |
| `opencode-qwen27-dflash-262k` | Qwen3.6-27B + DFlash | 262k, design / architecture |

`qwen36-nvfp4` is deprecated.

```bash
spark inference up opencode-qwen36-250k
```
