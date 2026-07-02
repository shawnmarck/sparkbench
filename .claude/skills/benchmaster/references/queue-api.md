# Benchmaster HTTP API

Proxied: `http://$SPARK_HOST/api/benchmaster/*` → `127.0.0.1:8770`  
Service: `spark-benchmaster-api.service` · Log: `/opt/spark/logs/benchmaster.log`

LAN/tailnet-unauthenticated (homelab trust model).

## Status & queue

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/benchmaster/status` | `control`, `current_job`, `counts`, `worker_alive`, `schedule_open` |
| GET | `/api/benchmaster/queue` | `items[]`, `control` |
| GET | `/api/benchmaster/runs` | Recent `summary.json` rows |
| GET | `/api/benchmaster/runs/<job_id>` | Job + summary + run_dir |
| GET | `/api/benchmaster/events` | Tail of `events.jsonl` |
| GET | `/api/benchmaster/stream?since=N` | SSE: `event: status` + `event: benchmaster` |

## Control

POST `/api/benchmaster/control`

```json
{ "action": "pause" }
```

Actions: `pause`, `resume`, `stop_after_current`, `abort_current_requeue_front`, `shutdown`

Optional schedule patch:

```json
{ "action": "resume", "schedule": { "enabled": true, "start_hour": 23, "end_hour": 7 } }
```

## Queue mutation

POST `/api/benchmaster/queue/add`

```json
{
  "type": "perf_sweep",
  "profile_id": "recipe-id",
  "inventory_path": "org/model-slug",
  "quant": "fp8",
  "note": "optional",
  "front": false,
  "harness": "terminal-bench@2.1",
  "agent": "terminus-2",
  "task_limit": 1
}
```

Types: `perf_sweep`, `ctx_ladder`, `kv_sweep`, `golden_workflow`, `intel_eval`

POST `/api/benchmaster/queue/reorder` — `{"job_ids":["bm-…","bm-…"]}`  
POST `/api/benchmaster/queue/remove` — `{"job_id":"bm-…"}` (not while running)

## Intel worker (remote)

| Method | Path | Body |
|--------|------|------|
| GET | `/api/benchmaster/jobs/available` | — · `gpu_busy`, `jobs[]` with `claimable` |
| GET | `/api/benchmaster/jobs/<id>/prereq` | Sparky load status |
| POST | `/api/benchmaster/jobs/<id>/claim` | `{"worker_id":"macbook-air","lease_secs":7200}` |
| POST | `/api/benchmaster/jobs/<id>/release` | `{"worker_id":"…","reason":"…"}` |
| POST | `/api/benchmaster/jobs/<id>/renew` | `{"worker_id":"…","extend_secs":7200}` |
| POST | `/api/benchmaster/jobs/<id>/complete` | `{"worker_id":"…","result":{…}}` |

Claim returns `409` when `gpu_busy` or job not claimable.

Prereq statuses: `pending` → `loading` → `ready` | `failed`

## Job fields (queue item)

| Field | Notes |
|-------|-------|
| `id` | `bm-YYYYMMDDHHMMSS-hex` |
| `type` | See above |
| `profile_id` | Recipe id |
| `inventory_path` | Catalog slug (rollup key) |
| `state` | `queued`, `running`, `done`, `failed` |
| `claimed_by` | intel only |
| `lease_expires_at` | intel only; expired → requeued |
| `prereq` | intel Sparky load sub-state |
| `progress` | `phase`, `step`, `total_steps`, `message` |

## Events (`events.jsonl`)

Common `event` values: `job_queued`, `job_start`, `phase_start`, `phase_done`, `phase_fail`, `job_done`, `control`, `intel_claim`, `intel_prereq_ready`, `intel_prereq_fail`, `intel_complete`, `intel_release`, `intel_lease_reaped`, `worker_error`

Stdout mirror: `AGENT_BENCHMASTER_EVENT {"ts":"…","event":"…",…}`

## CLI map

```bash
spark benchmaster status [--json]
spark benchmaster queue [--json]
spark benchmaster add <profile> [--type TYPE] [--inventory PATH] [--front]
spark benchmaster intel-available [--json]
spark benchmaster control <action>
spark benchmaster runs
```
