# Smoke — DwarfStar (ds4) on GB10

Pin: `data/ds4-dwarfstar.yaml` (Entrpi **v0.5.0**) · Model: `antirez/deepseek-v4-flash`

**Production recipe:** `antirez-deepseek-v4-flash-ds4` (0731 GGUF + DSpark).

## Prereqs

- Base: `…/DeepSeek-V4-Flash-…-imatrix-0731.gguf` (~81 GiB)
- Drafter: `…/DSpark-drafter-Q2K-Q8-0731.gguf` (~6.5 GiB)
- eugr and llama.cpp down (one GPU engine at a time)
- ≥ ~24 GiB MemAvailable before `up` (OOM preflight)

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

## Model Lab path (production profile)

```bash
spark inference up antirez-deepseek-v4-flash-ds4
spark inference status
spark inference bench      # bench-v2 @ recipe default fill (~14k at ctx 32k)
# Portal: Inference → filter chip "ds4"
```

Logs: `/opt/spark/logs/ds4-server.log` · OOM guard: `/opt/spark/logs/ds4-oom-guard.log`

## Open WebUI

ds4 defaults to **thinking mode** — visible replies look like internal reasoning in Chinese unless disabled.

- **Recommended:** connect Open WebUI to **`http://host.docker.internal:8002/v1`** (DwarfStar chat proxy — thinking off).
- **Or** pick model id **`deepseek-chat`** on the raw `:8000` backend.
- **Avoid** `deepseek-v4-flash` on `:8000` for casual chat unless you want thinking output.

Quick test via proxy:

```bash
curl -s http://127.0.0.1:8002/v1/chat/completions   -H 'Content-Type: application/json'   -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"hi"}],"max_tokens":32}'
```
