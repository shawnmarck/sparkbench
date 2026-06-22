# eugr vLLM stack upgrade (maintenance window)

**Notification only** — Spark detects upstream prebuilt wheel updates and shows a banner in the portal. Upgrades are **manual** during a maintenance window; tell a coding agent to run this runbook.

## What gets updated

| Layer | Source |
|-------|--------|
| vLLM wheels | [prebuilt-vllm-current](https://github.com/eugr/spark-vllm-docker/releases/tag/prebuilt-vllm-current) (nightly) |
| FlashInfer wheels | [prebuilt-flashinfer-current](https://github.com/eugr/spark-vllm-docker/releases/tag/prebuilt-flashinfer-current) |
| Docker image | `vllm-node:latest` via `build-and-copy.sh` |
| Runtime | `vllm_node` container on port **8000** |

**eugr** = [eugr/spark-vllm-docker](https://github.com/eugr/spark-vllm-docker) — Spark’s vLLM build for GB10 / NVFP4, not stock `vllm/vllm-openai`.

## Check for updates

```bash
spark engine eugr check          # human-readable
spark engine eugr check --json   # full payload (portal uses this via API)
```

Deployed pins live in `/opt/spark/run/eugr-stack-state.json`. Upstream checks are cached ~1h in `/opt/spark/run/eugr-check-cache.json`.

Portal: **Inference** tab shows a yellow banner when `update_available` is true.

## When to upgrade

- You see the portal banner or `spark engine eugr check` exits non-zero.
- No one needs inference for ~30–60 min (heavy profiles: longer first boot after rebuild).
- Prefer a quiet period — first profile load after image change may recompile CUDA graphs.

## Maintenance workflow (agent)

### 1. Preflight

```bash
spark inference status          # note active profile
spark engine eugr check --json
spark gpu                       # GPU should be idle or you will stop workloads next
```

### 2. Stop production inference

```bash
spark inference down            # stops active profile + engines
spark engine eugr down          # ensure vllm_node is gone
spark engine llama down         # if llama was up — one GPU engine at a time
```

Confirm: `curl -sf http://127.0.0.1:8000/v1/models` fails.

### 3. Refresh vendor + wheels

```bash
cd /opt/spark/vendor/spark-vllm-docker
git pull --ff-only              # recipe/script updates
./build-and-copy.sh             # downloads newer prebuilts when available, rebuilds image
```

`build-and-copy.sh` compares local `wheels/.vllm-commit` and `wheels/.flashinfer-commit` against the GitHub release pages (same logic as `spark engine eugr check`).

### 4. Canary smoke (recommended)

Run a **non-production** profile or the usual Qwen smoke on a spare port if you have a canary recipe; otherwise use the standard smoke profile:

```bash
spark engine eugr up
spark engine eugr logs          # wait for /v1/models
curl -sf http://127.0.0.1:8000/v1/models | head -c 400
curl -sf http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<served_name>","messages":[{"role":"user","content":"ping"}],"max_tokens":16}'
```

See also [smoke-vllm-eugr.md](./smoke-vllm-eugr.md).

### 5. Benchmark (optional but recommended for production profiles)

```bash
spark inference up <profile-id>   # e.g. qwen36-nvfp4
spark inference bench
spark bench latest <profile-id>
```

Compare tok/s to the previous run in the portal or `data/inference-benchmarks.yaml`.

### 6. Promote + record pins

If smoke/bench pass:

```bash
spark engine eugr record          # writes /opt/spark/run/eugr-stack-state.json
spark engine eugr check           # should report "matches upstream"
```

Bring back the desired production profile:

```bash
spark inference up <production-profile-id>
```

### 7. Verify portal

- http://sparky/ → Inference tab — no upgrade banner.
- http://sparky/api/inference/status — `eugr_stack.update_available` is `false`.

## Rollback

If the new image misbehaves:

```bash
spark inference down
spark engine eugr down
```

Rebuild from previous wheel backups (if `build-and-copy.sh` left them under `wheels/.backup-*`) or re-run `build-and-copy.sh` after restoring known-good `.vllm-commit` / `.flashinfer-commit` files, then:

```bash
spark engine eugr build           # alias for build-and-copy.sh
spark engine eugr up
spark engine eugr record
```

## State files

| File | Purpose |
|------|---------|
| `run/eugr-stack-state.json` | Deployed vLLM/FlashInfer commit pins + image id |
| `run/eugr-check-cache.json` | Cached upstream release parse (1h TTL) |
| `vendor/spark-vllm-docker/wheels/.vllm-commit` | Local wheel pin |
| `vendor/spark-vllm-docker/wheels/.flashinfer-commit` | Local wheel pin |

## Agent one-liner

> “Upgrade the eugr vLLM stack per `docs/runbooks/eugr-vllm-upgrade.md` — check, maintenance stop, build, smoke, bench, record, restore production profile.”