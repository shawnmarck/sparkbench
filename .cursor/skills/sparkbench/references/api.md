# SparkBench HTTP API reference

Base: `http://$SPARK_HOST` (nginx :80). All mutation routes are **LAN-unauthenticated**.

## Inference (`/api/inference/*` → :8767)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/inference/status` | Active profile, engine health, readiness. `loading.expect` has `typical_s` / `eta_s` / `pct` (observed ready time in `run/inference-load-times.json`, else tier bucket). Recipes include `load`. SGLang `active.multimodal` is live (`language_only` inverted, plus image caps). |
| GET | `/api/inference/recipes` | Recipe list + lifecycle |
| POST | `/api/inference/switch` | `{"profile":"<id>"}` — evict + load |
| POST | `/api/inference/down` | Stop active inference |
| POST | `/api/inference/bench` | Bench v2 on active profile |
| POST | `/api/inference/recipes/scaffold` | Auto-scaffold from weights |
| POST | `/api/inference/recipes/testing` | Mark recipe testing |
| POST | `/api/inference/recipes/promote` | Promote to production |
| POST | `/api/inference/recipes/discard` | Drop draft |
| GET | `/api/inference/benchmarks/<id>/history` | Bench history for profile |
| GET | `/api/inference/logs` | Engine log tail metadata |

CLI equivalents: `spark inference status|list|up|down|bench`, `spark recipe …`

## GPU & shelf

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/gpu` | GPU metrics JSON (portal widget). Includes `engine_load` (`running`, `waiting`, `max`, `kv_cache_pct`, tok/s sparkline) from vLLM/llama.cpp `/metrics`, or SGLang `/metrics` (`--enable-metrics`) with `/get_load` fallback. Slot cap from recipe `sglang.max_running`. |
| GET | `/api/shelf/status` | NAS mount + model sync state |
| POST | `/api/shelf/pull` | Pull model from shelf |
| POST | `/api/shelf/push` | Push model to shelf |
| POST | `/api/shelf/remove-local` | Queue local removal |

CLI: `spark gpu`, `spark shelf …`

## HuggingFace explore (`/api/hf/*`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/hf/status` | Worker health |
| GET | `/api/hf/queue` | Explore + download queue |
| POST | `/api/hf/queue` | Add explore/download item |
| POST | `/api/hf/queue/<id>/download` | Start download |
| POST | `/api/hf/queue/<id>/remove` | Remove queue item |
| GET | `/api/hf/search?q=…` | HF search |
| GET | `/api/hf/trending` | Trending models |
| GET | `/api/hf/model/<repo>` | Model metadata + variants |

CLI: `spark hf …` · Portal: **Explore** tab

## Activity & gateway

| Service | URL | Purpose |
|---------|-----|---------|
| Activity API | GET `/api/activity` | Client session rollups (:8769). `summary` includes `active_clients`, `sessions_1h`, `sessions_24h`, `avg_tok_s`, `apps`, and `vision` (`h1`/`h24` image-turn counts plus `last`). Recent rows may include `image_tokens`. `usage` has `windows` (`24h` / `30d` / `all`), per-profile totals (`usd` / `priced` from the ledger), and `days`. |
| Activity ledger | GET `/api/activity/ledger?profile=&grain=day\|month\|qtr\|year` | Per-profile token ledger with effective in/out rates. |
| Activity pricing | PUT `/api/activity/pricing` | Set `default` in/out $/1M and/or a grain `override` / `clear_override`. Stored in `run/inference-pricing.json`. |
| OpenAI gateway | `http://$SPARK_HOST:9000/v1` | Chat completions, model aliases |

## Engine upstream (direct)

| Engine | URL |
|--------|-----|
| eugr vLLM | `http://$SPARK_HOST:8000/v1` |
| llama.cpp | `http://$SPARK_HOST:8081/v1` |
| ds4 | `http://$SPARK_HOST:8000/v1` (mutually exclusive with eugr) |
| sglang | `http://$SPARK_HOST:8000/v1` (mutually exclusive with eugr; `/metrics` + `/get_load`) |
| flashnext | `http://$SPARK_HOST:8000/v1` (mutually exclusive with eugr; Mia Flash-Next vLLM `/metrics`) |

Prefer gateway `:9000` for agents — handles profile aliases and auto-switch.
