# SparkBench — installation and agent operations

Step-by-step guide for LLM agents installing and operating SparkBench on a DGX Spark (GB10).

Default paths: repo **`/opt/spark`**, weights **`/models`**, host **`sparky`**. Set `SPARK_HOST`, `SPARK_LAN_IP`, and `SPARK_USER` before install.

## Three surfaces

| Surface | When to use | Entry |
|---------|-------------|--------|
| **CLI** | Shell or SSH on the box | `/usr/local/bin/spark` |
| **HTTP API** | Network access, no shell | `http://$SPARK_HOST/api/…` |
| **Portal UI** | Visual state, Explore, Model Lab | `http://$SPARK_HOST/` |

Prefer CLI for mutations. Use HTTP when the harness only has `curl`.

## Step 1 — Clone and install

Run on the Spark box with sudo. Targets are idempotent.

```bash
git clone https://github.com/shawnmarck/sparkbench.git /opt/spark
cd /opt/spark
export SPARK_HOST="$(hostname -s)" SPARK_USER="$USER"

sudo bash install/spark-install bootstrap    # optional: host.env + passwordless install
sudo bash install/spark-install core         # portal, APIs, CLI, inventory
sudo bash install/spark-install engine eugr  # or: engine llama | engine ds4
sudo bash install/spark-install gateway      # :9000/v1 OpenAI proxy + activity API
```

Optional NAS shelf: `sudo bash install/spark-install nas` (CIFS creds in `/etc/spark/`).

After `core`, `spark install …` works too. Module index: `install/INSTALL.md`.

**Live box warning:** Do not run `spark-install core` while inference is serving. Use `spark-install module …` for surgical fixes.

## Step 2 — Protect host-local state

```bash
bash scripts/sparky-protect-runtime.sh
```

Skip-worktree on `data/inference-profiles.yaml` and `data/inference-benchmarks.yaml`. Never reset these from git without backup.

## Step 3 — Hugging Face and inventory

```bash
spark hf login                 # if downloading gated models
spark models inventory         # build portal/models.json
```

Inventory build needs venv: `/opt/spark/venv/bin/python scripts/spark-inventory-build.py`.

## Step 4 — Verify install

```bash
spark status
curl -fsS "http://${SPARK_HOST}/api/inference/status"
curl -fsS "http://${SPARK_HOST}/api/gpu"
```

Portal: `http://${SPARK_HOST}/`

## Operating loop

Track progress:

```
- [ ] spark inference list
- [ ] spark inference status
- [ ] spark inference up <profile-id>
- [ ] poll until ready (status or GET /api/inference/status)
- [ ] task (chat, bench, verify, …)
- [ ] spark inference down   # when freeing GPU
```

**One GPU engine at a time.** eugr and ds4 share port 8000; llama.cpp uses 8081.

Discover commands with `spark <group> help` — avoid bare `?` outside zsh.

## Common tasks

```bash
spark inference up qwen36-nvfp4
spark inference bench
spark recipe list
spark recipe scaffold <lab/slug> eugr
spark models verify set <lab/slug> works   # ONLY after bench v2 succeeds
spark hf search "deepseek v4"
spark hf queue add <repo>
spark shelf pull <lab/slug>
```

Remote agent: `ssh "$SPARK_USER@$SPARK_HOST" 'spark inference status'`

## HTTP API (no shell)

Base: `http://$SPARK_HOST` — LAN-unauthenticated.

```bash
BASE="http://${SPARK_HOST}"
curl -fsS "$BASE/api/inference/status"
curl -fsS -X POST "$BASE/api/inference/switch" \
  -H 'Content-Type: application/json' \
  -d '{"profile":"qwen36-nvfp4"}'
curl -fsS -X POST "$BASE/api/inference/bench"
curl -fsS "$BASE/api/hf/queue"
```

OpenAI gateway (after `gateway` install): `http://${SPARK_HOST}:9000/v1`

### Route reference

**Inference** (`→ :8767`): `GET /api/inference/status`, `GET /api/inference/recipes`, `POST /api/inference/switch`, `POST /api/inference/down`, `POST /api/inference/bench`, `POST /api/inference/recipes/scaffold|testing|promote|discard`

**GPU & shelf:** `GET /api/gpu`, `GET /api/shelf/status`, `POST /api/shelf/pull|push|remove-local`

**HuggingFace:** `GET /api/hf/queue|search|trending|model/<repo>`, `POST /api/hf/queue`, `POST /api/hf/queue/<id>/download|remove`

**Activity:** `GET /api/activity` · **Engines:** eugr/ds4 `:8000/v1`, llama `:8081/v1`

## Rules

1. **`works` verify** only after successful **bench v2** — not load-only smoke.
2. **Recipes auto-scaffold** — fix `scaffold_error` via code routing; hand-write YAML only for MoE/multimodal/DFlash/ds4/MTP edge cases.
3. **LAN trust only** — do not expose mutation APIs on :80 to the WAN.
4. **Secrets** — `/etc/spark/smb-credentials-models`, `HF_TOKEN`; never commit.

## Further reading (in repo)

| Doc | Topic |
|-----|--------|
| `AGENTS.md` | Layout and code touchpoints |
| `docs/reference/spark-cli.md` | Full CLI |
| `docs/runbooks/new-model-golden-benchmark.md` | Golden audit |
| `docs/runbooks/sparky-live-sync.md` | Pull code on a live box |
