# SparkInfer (Mia / 0xSero) smoke

Pin: `data/sparkinfer-mia.yaml`. Profile: `0xsero-deepseek-v4-flash-0731-sparkinfer`.

This is **not** the Entrpi ds4 GGUF golden (`antirez-deepseek-v4-flash-ds4`).

## Prereqs

- TP1 checkpoint: `/models/0xsero/deepseek-v4-flash-0731-spark/data/tp1/rank-sliced-tp1-manifest.json`
- Image: `ghcr.io/0xsero/deepseek-v4-flash-0731-spark-sparkinfer` (pinned digest in the pin file)
- eugr / llama / ds4 down (one GPU engine)
- ≥ 114 GiB MemAvailable before `up`

```bash
# one-time weights (no GPU)
cd /opt/spark/services/sparkinfer-mia
HF_CACHE=/models/0xsero/deepseek-v4-flash-0731-spark/hf-hub ./download.sh
```

## Engine smoke

```bash
spark engine eugr down
spark engine llama down
spark engine ds4 down
spark engine sparkinfer up
spark engine sparkinfer status    # wait until /v1/models lists deepseek-v4-flash-0731
curl -sf http://127.0.0.1:8000/v1/models | head
spark engine sparkinfer down
```

## Model Lab path

```bash
spark inference up 0xsero-deepseek-v4-flash-0731-sparkinfer --preset ship
spark inference status
# Gateway: sparky / sparky-think / deepseek-v4-flash-0731 / deepseek-v4-flash-0731-think
spark inference bench      # bench v2 — required before verify works
spark inference down
```

Presets: `ship` (384k / 1 seq), `dual` (128k / 2), `quad` (64k / 4). Do not lower `MAX_NUM_BATCHED_TOKENS` below 8224.

Logs: `/opt/spark/logs/sparkinfer.log` and `docker logs` on `deepseek-v4-flash-spark-*`.
