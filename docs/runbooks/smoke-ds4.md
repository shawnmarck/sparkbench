# Smoke — DwarfStar (ds4) on GB10

Pin: `data/ds4-dwarfstar.yaml` · Model: `antirez/deepseek-v4-flash`

## Prereqs

- Weights at `/models/antirez/deepseek-v4-flash/gguf/*.gguf` (~81 GB)
- eugr and llama.cpp down (one GPU engine at a time)

## Install / build

```bash
sudo bash /opt/spark/install/spark-install engine ds4
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

## Open WebUI

ds4 defaults to **thinking mode** — visible replies look like internal reasoning in Chinese unless disabled.

- **Recommended:** connect Open WebUI to **`http://host.docker.internal:8002/v1`** (DwarfStar chat proxy — thinking off).
- **Or** pick model id **`deepseek-chat`** on the raw `:8000` backend.
- **Avoid** `deepseek-v4-flash` on `:8000` for casual chat unless you want thinking output.

Quick test via proxy:

```bash
curl -s http://127.0.0.1:8002/v1/chat/completions   -H 'Content-Type: application/json'   -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"hi"}],"max_tokens":32}'
```
