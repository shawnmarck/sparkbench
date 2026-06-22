# Smoke — DwarfStar (ds4) on GB10

Pin: `data/ds4-dwarfstar.yaml` · Model: `antirez/deepseek-v4-flash`

## Prereqs

- Weights at `/models/antirez/deepseek-v4-flash/gguf/*.gguf` (~81 GB)
- eugr and llama.cpp down (one GPU engine at a time)

## Install / build

```bash
sudo bash /opt/spark/install/22-ds4-dwarfstar.sh
```

## Engine smoke

```bash
spark engine eugr down
spark engine llama down
spark engine ds4 up
spark engine ds4 status    # wait until /v1/models lists deepseek-v4-flash
curl -sf http://127.0.0.1:8000/v1/models | head
spark engine ds4 down
```

## Model Lab path

```bash
spark recipe scaffold antirez/deepseek-v4-flash ds4
spark recipe testing antirez-deepseek-v4-flash-ds4
spark inference up antirez-deepseek-v4-flash-ds4
spark inference bench
spark recipe works antirez-deepseek-v4-flash-ds4
```

Logs: `/opt/spark/logs/ds4-server.log`
