# TASK-001: Client activity dashboard widget

| Field | Value |
|-------|-------|
| **Status** | ready |
| **Priority** | Seq 3 |
| **Owner** | — |
| **PR policy** | **One PR** — gateway instrumentation + activity API + System widget |
| **Depends on** | `spark-inference-gateway` running (`install/23-inference-gateway.sh`) |
| **Primary files** | `scripts/spark-inference-gateway.py`, `scripts/spark-client-activity.py` (new), `portal/index.html`, `install/24-client-activity-api.sh` (new) |

## Problem

The System dashboard shows GPU, memory, inference profile pills, and containers — but **no per-client activity**. Operators want at-a-glance: how many clients are connected, source IP, which app, recent sessions (1h/24h), avg tok/s, total tokens.

### Data inventory (today)

| Source | Client activity? |
|--------|------------------|
| `GET /api/gpu` | No — host metrics + Hermes up probe only |
| `GET /api/inference/status` | No — bench tok/s, not live throughput |
| Gateway `:9000/v1` | Ephemeral stderr access logs only |
| eugr / llama / ds4 engines | Not scraped per-client |
| Open WebUI / Hermes | No spark API integration |

**Observation point:** instrument **`spark-inference-gateway`** — stable front door for Hermes, Open WebUI, agents.

## Requirements

### Functional

1. **`GET /api/activity`** — summary + recent sessions; optional `?window=1h|24h`.
2. **Gateway instrumentation** — record `POST /v1/chat/completions` and `POST /v1/completions` (stream + non-stream): timestamp, client IP, User-Agent, model, profile, engine, duration, tokens, tok/s.
3. **App classification** — heuristic from User-Agent + optional `X-Spark-Client` header (`hermes`, `open-webui`, `opencode`, `script`, `unknown`).
4. **Active clients** — in-memory map (IP + app, last_seen, in-flight) with ~5 min TTL.
5. **Persistence** — append-only `run/inference-activity.jsonl` (gitignored); 1h/24h rollups; rotation cap (~7d / 50MB).
6. **System tab widget** — summary row + recent sessions table (last 20); stale/offline when API down.

### Non-functional

- Non-blocking on streaming hot path
- Strip `Authorization` from logs
- LAN-only trust model (document sensitivity)

### Out of scope (v1)

- vLLM Prometheus scrape (engine-level, not per-client)
- Open WebUI / Hermes internal session APIs
- Per-user identity beyond IP + UA
- Direct `:8000`/`:8081` bypass traffic

## Acceptance criteria

- [ ] `curl http://sparky/api/activity` returns `summary` + `recent[]`
- [ ] Gateway POST to `:9000/v1/chat/completions` creates a session row within 2s
- [ ] Streaming completions produce **one** session row at stream end
- [ ] System tab shows Client activity section; updates on visible System view
- [ ] API down → graceful empty state; `gpuPoll` unaffected
- [ ] Events survive gateway restart (jsonl on disk)
- [ ] Install script + nginx location documented; `AGENT.md` updated

## Test plan

1. Unit: jsonl → aggregator rollups and avg tok/s
2. Smoke: curl chat completion via `:9000` → verify `/api/activity`
3. Streaming: `"stream":true` → single row with tok/s
4. Portal: System tab populates; hidden tab stops extra polls
5. Regression: gateway forwarding, `/api/gpu`, `/api/inference/status` unchanged

## Implementation notes

```text
Clients → spark-inference-gateway :9000  (instrument)
              ↓ append
         run/inference-activity.jsonl
              ↑ read
         spark-client-activity API :8769
              ↓
         nginx /api/activity → portal widget
```

Insert widget in System card after "Inference & containers" (`portal/index.html`). Use snapshot-diff render like `renderNavHermes`.

**Session schema (draft):** `id`, `at`, `client_ip`, `app`, `user_agent`, `model`, `profile`, `engine`, `duration_ms`, `prompt_tokens`, `completion_tokens`, `tok_s`, `stream`, `status`.

## Completion log

| Date | Owner | Result | Commit |
|------|-------|--------|--------|
| — | — | — | — |
