# SparkBench — installation and agent operations

Step-by-step guide for installing and operating SparkBench on a DGX Spark (GB10).

Default paths: repo **`/opt/spark`**, weights **`/models`**, host **`sparky`**. Set `SPARK_HOST`, `SPARK_LAN_IP`, and `SPARK_USER` before install.

## Three surfaces

| Surface | When to use | Entry |
|---------|-------------|--------|
| **CLI** | Shell or SSH on the box | `/usr/local/bin/spark` |
| **HTTP API** | Network access, no shell | `http://$SPARK_HOST/api/…` |
| **Portal UI** | Visual state, Explore, Model Lab | `http://$SPARK_HOST/` |

Prefer CLI for mutations. Use HTTP when the harness only has `curl`.

## Step 1 — Clone and install

**One command** (fresh box):

```bash
curl -fsSL https://raw.githubusercontent.com/shawnmarck/sparkbench/main/scripts/bootstrap-sparkbench.sh | sudo bash
```

Or run the steps by hand. Targets are idempotent.

```bash
git clone https://github.com/shawnmarck/sparkbench.git /opt/spark
cd /opt/spark
export SPARK_HOST="$(hostname -s)" SPARK_USER="$USER"

sudo bash install/spark-install quickstart       # bootstrap + core
sudo bash install/spark-install engine eugr      # or: engine llama | engine ds4
sudo bash install/spark-install gateway          # :9000/v1 + activity API
```

Optional NAS shelf: `sudo bash install/spark-install nas` (CIFS creds in `/etc/spark/`).

After `core`, `spark install …` works too. Module index: `install/INSTALL.md`.

**Live box:** do not run `spark-install core` while inference is serving. Use `spark-install module …` for surgical fixes.

## Optional — Agent harness skill

Skip this if the agent already runs **inside** a clone of `/opt/spark`. Project skills live at `.claude/skills/sparkbench/` and `.cursor/skills/sparkbench/`.

When the harness works **outside** the repo (another project, SSH-only ops), copy the skill into the home directory:

```bash
sudo bash install/spark-install extras agent-skill
```

Or as your user, without sudo:

```bash
bash install/modules/extras/agent-skill.sh
```

Installs `SKILL.md` + API reference to `~/.claude/skills/sparkbench/` and `~/.cursor/skills/sparkbench/`. Limit targets with `SPARK_HARNESS=claude`, `cursor`, or `both` (default).

## Step 2 — Protect host-local state

```bash
bash scripts/sparky-protect-runtime.sh
```

Skip-worktree on `data/inference-profiles.yaml` and `data/inference-benchmarks.yaml`. Never reset these from git without a backup.

## Step 3 — Hugging Face and inventory

```bash
spark hf login                 # gated models
spark models inventory         # build portal/models.json
```

Inventory build needs the venv: `/opt/spark/venv/bin/python scripts/spark-inventory-build.py`.

## Step 4 — Verify install

```bash
spark status
curl -fsS "http://${SPARK_HOST}/api/inference/status"
curl -fsS "http://${SPARK_HOST}/api/gpu"
```

Portal: `http://${SPARK_HOST}/`

## Operating loop

```
- [ ] spark inference list
- [ ] spark inference status
- [ ] spark inference up <profile-id>
- [ ] poll until ready (status or GET /api/inference/status)
- [ ] task (chat, bench, verify, …)
- [ ] spark inference down   # when freeing the GPU
```

**One GPU engine at a time.** eugr and ds4 share port 8000; llama.cpp uses 8081.

Discover commands with `spark <group> help`. Avoid bare `?` outside zsh.

Everyday Qwen3.6-35B-A3B profile: `opencode-qwen36-250k`. `qwen36-nvfp4` is deprecated.

## Common tasks

```bash
spark inference up opencode-qwen36-250k
spark inference bench
spark recipe list
spark recipe scaffold <lab/slug> eugr
spark models verify set <lab/slug> works   # only after bench v2 succeeds
spark hf search "deepseek v4"
spark hf queue add <repo>
spark shelf pull <lab/slug>
spark benchmaster status
```

Remote agent: `ssh "$SPARK_USER@$SPARK_HOST" 'spark inference status'`

## HTTP API (no shell)

Base: `http://$SPARK_HOST`. LAN-unauthenticated.

```bash
BASE="http://${SPARK_HOST}"
curl -fsS "$BASE/api/inference/status"
curl -fsS -X POST "$BASE/api/inference/switch" \
  -H 'Content-Type: application/json' \
  -d '{"profile":"opencode-qwen36-250k"}'
curl -fsS -X POST "$BASE/api/inference/bench"
curl -fsS "$BASE/api/hf/queue"
curl -fsS "$BASE/api/benchmaster/status"
```

OpenAI gateway (after `gateway` install): `http://${SPARK_HOST}:9000/v1`. Use model `sparky` unless you need a concrete served name.

### Route reference

**Inference** (`→ :8767`): `GET /api/inference/status`, `GET /api/inference/recipes`, `POST /api/inference/switch`, `POST /api/inference/down`, `POST /api/inference/bench`, `POST /api/inference/recipes/scaffold|testing|promote|discard`

**GPU & shelf:** `GET /api/gpu`, `GET /api/shelf/status`, `POST /api/shelf/pull|push|remove-local`

**Hugging Face:** `GET /api/hf/queue|search|trending|model/<repo>`, `POST /api/hf/queue`, `POST /api/hf/queue/<id>/download|remove`

**Activity:** `GET /api/activity`

**Benchmaster:** `GET /api/benchmaster/status|queue`, `POST /api/benchmaster/control`, `POST /api/benchmaster/queue/add`

**Engines:** eugr/ds4 `:8000/v1`, llama `:8081/v1`

## Rules

1. **`works` verify** only after successful **bench v2**, not a load-only smoke.
2. **Recipes auto-scaffold.** Fix `scaffold_error` in the router. Hand-write YAML only for MoE / multimodal / DFlash / ds4 / MTP.
3. **LAN trust only.** Do not expose mutation APIs on :80 to the WAN.
4. **Secrets** stay in `/etc/spark/smb-credentials-models` and `HF_TOKEN`. Never commit them.

## Further reading

| Doc | Topic |
|-----|--------|
| `AGENTS.md` | Layout and code touchpoints |
| `docs/reference/spark-cli.md` | Full CLI |
| `docs/reference/inference-stack.md` | Recipes, gateway, engines |
| `docs/runbooks/new-model-golden-benchmark.md` | Golden audit |
| `docs/runbooks/benchmaster-agent.md` | Overnight queue |
| `docs/runbooks/sparky-live-sync.md` | Pull code on a live box |
