# SparkBench HTTP API reference

Base: `http://$SPARK_HOST` (nginx :80). All mutation routes are **LAN-unauthenticated**.

## Inference (`/api/inference/*` → :8767)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/inference/status` | Active profile, engine health, readiness |
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
| GET | `/api/gpu` | GPU metrics JSON (portal widget) |
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
| Activity API | GET `/api/activity` | Client session rollups (:8769) |
| OpenAI gateway | `http://$SPARK_HOST:9000/v1` | Chat completions, model aliases |

## Install agent (`/api/install/*` → :8771)

Privileged allowlisted `spark-install` jobs. Bind loopback; nginx proxies. Mutations require header `X-Spark-Install-Token` matching `/etc/spark/install-token`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/install/status` | Service probes + active job |
| GET | `/api/install/targets` | Allowlisted targets |
| POST | `/api/install/jobs` | Start job `{target, args?}` |
| GET | `/api/install/jobs/{id}` | Job state |
| GET | `/api/install/jobs/{id}/stream` | SSE log tail |
| POST | `/api/install/jobs/{id}/cancel` | Best-effort cancel |

## Engine upstream (direct)

| Engine | URL |
|--------|-----|
| eugr vLLM | `http://$SPARK_HOST:8000/v1` |
| llama.cpp | `http://$SPARK_HOST:8081/v1` |
| ds4 | `http://$SPARK_HOST:8000/v1` (mutually exclusive with eugr) |

Prefer gateway `:9000` for agents — handles profile aliases and auto-switch.

## Spark operator (`/api/operator/*` → :8772)

Loopback Hermes adapter for Portal v2. Chat uses an out-of-band provider and
typed SparkBench MCP tools. Mutations are proposals and cannot execute before
an explicit confirmation.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/operator/status` | Runtime, provider, goals, checks, pending actions |
| POST | `/api/operator/turns` | Start an asynchronous chat turn |
| GET | `/api/operator/turns/<id>` | Read turn state/result |
| GET | `/api/operator/turns/<id>/stream` | SSE turn updates |
| GET/POST | `/api/operator/goals` | List/create durable goals |
| GET | `/api/operator/checks` | List Spark-owned Hermes cron jobs |
| POST | `/api/operator/proposals` | Prepare an allowlisted action |
| POST | `/api/operator/proposals/<id>/confirm` | Execute the exact proposed action |
| POST | `/api/operator/proposals/<id>/cancel` | Cancel a proposal |
| GET | `/api/operator/models?provider=<slug>&refresh=0` | Hermes provider catalog and live/cached models |
| GET/POST | `/api/operator/settings` | Redacted state / confirmed Hermes provider + model selection |

Confirming an `install` proposal and changing provider settings also require
the `X-Spark-Install-Token` header.

## Benchmaster (`/api/benchmaster/*` → :8770)

Queue control for **perf sweeps** (Sparky GPU) and **intel evals** (remote Harbor worker). Portal: `#benchmaster` · Log: `/opt/spark/logs/benchmaster.log`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/benchmaster/status` | Control mode, current job, counts, worker_alive |
| GET | `/api/benchmaster/queue` | Full queue snapshot |
| GET | `/api/benchmaster/runs` | Completed run summaries |
| GET | `/api/benchmaster/runs/<job_id>` | Job + summary + artifacts path |
| GET | `/api/benchmaster/events` | Event log tail |
| GET | `/api/benchmaster/stream?since=N` | SSE status + events |
| GET | `/api/benchmaster/jobs/available` | Claimable `intel_eval` jobs (`gpu_busy` flag) |
| GET | `/api/benchmaster/jobs/<id>/prereq` | Intel model-load status on Sparky |
| POST | `/api/benchmaster/queue/add` | Enqueue job (see body below) |
| POST | `/api/benchmaster/queue/reorder` | `{"job_ids":[…]}` |
| POST | `/api/benchmaster/queue/remove` | `{"job_id":"bm-…"}` |
| POST | `/api/benchmaster/control` | `{"action":"pause\|resume\|stop_after_current\|abort_current_requeue_front"}` |
| POST | `/api/benchmaster/jobs/<id>/claim` | Remote worker: `{"worker_id":"…","lease_secs":7200}` |
| POST | `/api/benchmaster/jobs/<id>/release` | Release claim |
| POST | `/api/benchmaster/jobs/<id>/renew` | Extend lease |
| POST | `/api/benchmaster/jobs/<id>/complete` | Post Harbor results |

**queue/add body:** `type` (`perf_sweep` | `ctx_ladder` | `kv_sweep` | `golden_workflow` | `intel_eval`), `profile_id`, optional `inventory_path`, `quant`, `note`, `front`, `harness`, `agent`, `task_limit`.

CLI: `spark benchmaster status|queue|add|intel-available|control|runs`

Agent skill: `.claude/skills/benchmaster/SKILL.md` · Runbook: `docs/runbooks/benchmaster-agent.md`
