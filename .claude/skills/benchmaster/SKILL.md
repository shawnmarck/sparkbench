---
name: benchmaster
description: >-
  Operate the Benchmaster queue on SparkBench: perf sweeps (Sparky GPU), intel evals
  (Mac/techno Harbor worker), pause/abort/resume, triage failures, enqueue recipes.
  Use when the user mentions Benchmaster, bench queue, perf_sweep, ctx_ladder, kv_sweep,
  intel_eval, overnight benchmarks, terminal-bench, Harbor worker, or conversational
  queue control on sparky — including tmux/OpenCode sessions supervising long runs.
---

# Benchmaster agent

Extends [sparkbench](../sparkbench/SKILL.md). SparkBench runs **models**; Benchmaster runs **jobs** against **recipes** (perf + intel axes).

## Three runners (do not confuse)

| Runner | Where | Job types | You control via |
|--------|-------|-----------|-----------------|
| **Sparky GPU worker** | `spark-benchmaster-api` systemd thread | `perf_sweep`, `ctx_ladder`, `kv_sweep`, `golden_workflow` | `/api/benchmaster/control`, portal **Benchmaster** tab |
| **Remote intel worker** | Mac or techno (`spark-benchmaster-worker.py`) | `intel_eval` | claim/complete API; config `~/.config/sparkbench/worker.yaml` |
| **You (this agent)** | SSH on sparky or HTTP | — | curl, `spark benchmaster`, triage logs — **supervise**, don't replace the workers |

**One GPU at a time.** Perf jobs and intel prereq both call `spark inference up`. Never start a manual `spark inference up` while Benchmaster mode is `running` unless you paused the queue first.

## Surfaces

| Surface | Use |
|---------|-----|
| `GET/POST http://$SPARK_HOST/api/benchmaster/*` | Status, queue, control, SSE stream |
| `spark benchmaster …` | Same when CLI installed (`sudo install -m 755 /opt/spark/scripts/spark /usr/local/bin/spark`) |
| Portal | `http://$SPARK_HOST/#benchmaster` |
| `tail -F /opt/spark/logs/benchmaster.log` | Worker + phase subprocess output |
| `run/benchmaster/events.jsonl` | Durable event log |
| `run/benchmaster/runs/<job_id>/` | Per-job phase logs + `summary.json` |
| `AGENT_BENCHMASTER_EVENT {…}` stdout | Live events from API worker (for `/loop` babysit) |

Full HTTP table: [references/queue-api.md](references/queue-api.md) (also in [sparkbench references/api.md](../sparkbench/references/api.md)).

Persistent state:

```
run/benchmaster/queue.yaml      # queue + control mode
run/benchmaster/events.jsonl
run/benchmaster/runs/<job_id>/
data/benchmaster-results.yaml   # intel rollup (host-local)
```

## First actions on every task

```bash
curl -s http://sparky/api/benchmaster/status | python3 -m json.tool
curl -s http://sparky/api/benchmaster/queue | python3 -m json.tool
spark inference status    # if on box
```

Read `control.mode` (`paused` | `running` | `stopped`), `current_job`, and failed job `error` + `run/benchmaster/runs/<id>/summary.json`.

## Control plane

| User intent | Action |
|-------------|--------|
| Start overnight sweeps | `POST /api/benchmaster/control` `{"action":"resume"}` |
| Free GPU now (after current step) | `{"action":"pause"}` |
| Finish this step then stop | `{"action":"stop_after_current"}` |
| Kill step, requeue at front | `{"action":"abort_current_requeue_front"}` |

CLI: `spark benchmaster control pause|resume|stop_after_current|abort_current_requeue_front`

**Pause** and **abort** call `spark inference down` when safe. Expect the current perf phase to take minutes–hours (golden cell, kv_sweep, ctx_ladder).

## Enqueue jobs

### Perf sweep (all three phases: golden cell → kv_sweep → ctx_ladder)

```bash
curl -s -X POST http://sparky/api/benchmaster/queue/add \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "perf_sweep",
    "profile_id": "deepreinforce-ai-ornith-1-0-35b-fp8-eugr",
    "inventory_path": "deepreinforce-ai/ornith-1.0-35b",
    "note": "tier 2 perf",
    "front": false
  }'
```

CLI:

```bash
spark benchmaster add <profile_id> --type perf_sweep --inventory lab/slug [--front]
```

Single phase only:

```bash
spark benchmaster add <profile_id> --type ctx_ladder   # or kv_sweep, golden_workflow
```

**Draft recipes:** FP8/NVFP4 ornith profiles live in `recipes/drafts/`. Golden phase benches the job's `profile_id` (not `golden-recipes.yaml` llama mapping). `spark-golden-bench.py` resolves drafts automatically.

### Intel eval (Harbor on Mac/techno; Sparky loads model on claim)

```bash
spark benchmaster add <profile_id> --type intel_eval \
  --inventory deepreinforce-ai/ornith-1.0-35b \
  --harness terminal-bench@2.1 --agent terminus-2 \
  --task-limit 1    # smoke only
```

Check claimability (GPU must be idle):

```bash
spark benchmaster intel-available
```

Remote worker (on Mac, not Sparky):

```bash
python3 spark-benchmaster-worker.py once   # or loop
```

Config template: `install/worker.yaml.example` → `~/.config/sparkbench/worker.yaml`.

## Triage failed jobs

1. `summary.json` in `run/benchmaster/runs/<job_id>/` — which phase failed?
2. Phase log: `golden_workflow.log`, `kv_sweep.log`, `ctx_ladder.log`
3. Common fixes:

| Symptom | Fix |
|---------|-----|
| `missing recipe` | Recipe in `recipes/drafts/` — ensure latest `spark-golden-bench.py` on box; restart `spark-benchmaster-api` after code pull |
| Golden ran wrong quant | Old bug (inventory golden map) — fixed; reset job to `queued` and re-run |
| `load_fail` / ctx mismatch | Check recipe `context.presets.golden`, eugr service YAML, `--language-model-only` for MoE |
| `gpu_busy` on intel claim | Wait for perf job to finish or pause queue |
| Harbor failures | Mac worker logs; gateway `http://sparky:9000/v1/models`; tailnet latency |

Re-run failed perf job: edit `run/benchmaster/queue.yaml` set `state: queued`, clear `error`/`finished_at`, or remove + re-add with `--front`.

## Multi-quant workflow (example: ornith)

1. Tier 1 headline compare already done (`spark-ornith-quant-compare.sh`).
2. Tier 2: queue `perf_sweep` per quant recipe (FP8, NVFP4, …).
3. When GPU free: queue `intel_eval` per quant (or one golden quant first).
4. Do **not** hand-write recipe YAML — fix router in `spark-inference.py` if scaffold fails.

## Live monitoring

```bash
# SSE (status every 2s + events)
curl -N http://sparky/api/benchmaster/stream

tail -F /opt/spark/logs/benchmaster.log
```

For unattended babysit, poll `GET /api/benchmaster/status` every 5–15m; on `failed` or stuck `running` > expected duration, inspect logs before auto-abort.

## Downloads (LLM propose → human approve)

Do **not** auto-download weights. Propose shortlist → user approves → `spark hf queue add …` (existing HF pipeline). Hook to auto-enqueue perf+intel after download is Phase 3b (not built).

## Code touchpoints

| Change | File |
|--------|------|
| Queue schema, phases, claim API | `scripts/spark-benchmaster.py` |
| HTTP :8770 | `scripts/spark-benchmaster-api.py` |
| nginx proxy | `install/common.sh` → `/api/benchmaster/` |
| Portal tab | `portal/assets/spark-benchmaster.js`, `#benchmaster` |
| Intel worker (portable) | `scripts/spark-benchmaster-worker.py` |
| Golden probes / drafts | `scripts/spark-golden-bench.py` |

After editing `spark-benchmaster-api.py`: `sudo bash install/spark-install restart inference-api` is **wrong** — use `sudo systemctl restart spark-benchmaster-api.service`.

After editing `spark-benchmaster.py`: restart `spark-benchmaster-api` (worker thread loads core at startup).

## Long-lived session (OpenCode + tmux)

For conversational supervision on Sparky, use a persistent tmux session. Full bootstrap: [docs/runbooks/benchmaster-agent.md](../../../docs/runbooks/benchmaster-agent.md).

```bash
tmux new -s benchmaster
cd /opt/spark
opencode    # agent LLM separate from model-under-test
```

Attach later: `tmux attach -t benchmaster`.

**Bench control** (queue, curl, spark CLI) is separate from **model-under-test** (gateway :9000 during intel runs).

## Rules

1. Pause Benchmaster before manual `spark inference up` / engine swaps.
2. Never run eugr + llama engines concurrently.
3. Don't commit `data/benchmaster-results.yaml`, `run/benchmaster/queue.yaml` unless user asks — host-local runtime.
4. `spark models verify set … works` only after bench v2 / golden audit policy — Benchmaster perf sweeps populate `bench_matrix`, not verify status directly.
5. Only one remote intel worker should claim at a time until lease/reaper proven in production.
