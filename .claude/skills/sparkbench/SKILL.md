---
name: sparkbench
description: >-
  Install and operate SparkBench on a DGX Spark (GB10): spark CLI, HTTP control APIs,
  and portal UI. Use when the user mentions SparkBench, sparky, spark inference,
  model lab, golden audit, spark-install, /models, HF explore queue, gateway :9000,
  or running benchmarks on a Spark box — including remote SSH or HTTP-only harnesses.
---

# SparkBench agent skill

Operate a **single Spark box** end-to-end: install, switch models, bench, verify, explore HF — via **CLI** (preferred), **HTTP API** (no shell), or **Portal UI** (human sanity check).

Default paths: repo **`/opt/spark`**, weights **`/models`**, host alias **`sparky`**. Override with env below.

## Three surfaces

| Surface | When to use | Entry |
|---------|-------------|--------|
| **CLI** | Shell/SSH on the box (or `ssh sparky '…'`) | `/usr/local/bin/spark` |
| **HTTP API** | Agent has network, no shell | `http://$SPARK_HOST/api/…` |
| **Portal UI** | Visual state, Explore tab, Model Lab | `http://$SPARK_HOST/` |

Same backend. Prefer CLI for mutations; use HTTP when the harness only has `curl`.

## Environment

```bash
export SPARK_HOST=sparky          # or LAN IP / mDNS name
export SPARK_ROOT=/opt/spark
export SPARK_USER=spark           # runtime user for services
# Optional: HF_TOKEN for gated downloads (never commit)
```

**Remote agent pattern:** `ssh "$SPARK_USER@$SPARK_HOST" 'spark inference status'`

**HTTP base:** `http://${SPARK_HOST}` (nginx :80 proxies APIs)

## Fresh install (empty Spark box)

Run on the box with sudo. Idempotent — safe to re-run individual targets.

```bash
git clone https://github.com/shawnmarck/sparkbench.git /opt/spark
cd /opt/spark
export SPARK_HOST="$(hostname -s)" SPARK_USER="$USER"

sudo bash install/spark-install bootstrap    # optional: host.env + passwordless install
sudo bash install/spark-install core         # portal, APIs, CLI, inventory
sudo bash install/spark-install engine eugr  # or: engine llama | engine ds4
sudo bash install/spark-install gateway      # :9000/v1 OpenAI proxy + activity API

bash scripts/sparky-protect-runtime.sh       # skip-worktree on host-local YAML
spark hf login                               # if downloading from HuggingFace
spark models inventory                       # build portal/models.json
```

Optional NAS shelf: `sudo bash install/spark-install nas` (needs CIFS creds in `/etc/spark/`).

Full module index: `install/INSTALL.md`. Deep API routes: [references/api.md](references/api.md).

**Live box warning:** Do **not** run `spark-install core` while inference is serving — it restarts APIs and rewrites nginx. Use `spark-install module core/inference-api-restart.sh` (or other `module …` paths) for surgical fixes.

## Agent operating loop

Copy and track:

```
- [ ] spark status                    # GPU + inference overview
- [ ] spark inference list            # valid profile ids (enabled in inference-profiles.yaml)
- [ ] spark inference status          # active profile + engine health
- [ ] spark inference up <profile-id> # evicts current engine; may take minutes
- [ ] poll until ready                # status or GET /api/inference/status
- [ ] task (chat, bench, verify, …)
- [ ] spark inference down            # when freeing GPU for another profile
```

Discover with `spark <group> help` — avoid bare `?` in non-zsh shells.

**One GPU engine at a time.** eugr and ds4 both use port 8000; llama.cpp uses 8081. Stop one before starting another: `spark engine eugr down`, `spark engine llama down`, etc.

## Common tasks (CLI)

```bash
# Switch + smoke
spark inference up qwen36-nvfp4
spark inference status
curl -sf "http://${SPARK_HOST}:8000/v1/models" | head

# Benchmark active profile (writes host-local results)
spark inference bench

# Model Lab
spark recipe list
spark recipe scaffold <lab/slug> eugr    # or llamacpp / ds4
spark models verify set <lab/slug> works # ONLY after bench v2 succeeds

# HuggingFace explore + download
spark hf search "deepseek v4"
spark hf queue add <repo> --variant <path>
spark hf queue list

# Shelf (optional NAS)
spark shelf status
spark shelf pull <lab/slug>

# Engines (build/smoke — install targets wrap these)
spark engine eugr status
spark engine llama up
spark engine ds4 build
```

Install shortcuts: `spark install core`, `spark install engine eugr`, `spark install gateway` (same as `sudo bash install/spark-install …`).

## HTTP-only harness

When you cannot run `spark` locally, use LAN-trusted APIs (no auth):

```bash
BASE="http://${SPARK_HOST}"

curl -fsS "$BASE/api/gpu" | jq .
curl -fsS "$BASE/api/inference/status" | jq .
curl -fsS "$BASE/api/shelf/status" | jq .

# Switch profile
curl -fsS -X POST "$BASE/api/inference/switch" \
  -H 'Content-Type: application/json' \
  -d '{"profile":"qwen36-nvfp4"}'

# Bench active profile
curl -fsS -X POST "$BASE/api/inference/bench"

# HF queue (Explore tab backend)
curl -fsS "$BASE/api/hf/queue" | jq .
curl -fsS -X POST "$BASE/api/hf/queue" \
  -H 'Content-Type: application/json' \
  -d '{"repo":"org/model","intent":"download"}'
```

OpenAI-compatible chat (after `gateway` install): `http://${SPARK_HOST}:9000/v1` — aliases + auto-switch across profiles.

More routes: [references/api.md](references/api.md).

## Portal UI map

| Tab / page | Purpose |
|------------|---------|
| **System** | GPU widget, client activity, service links |
| **Models** | Catalog grid, verification, Model Lab detail |
| **Inference** | Profile switch, bench, logs link |
| **Explore** | HF browse, shortlist compare, download queue |

Human URL: `http://${SPARK_HOST}/` · models page: `/models.html`

## Rules (do not break)

1. **`works` verify tag** only after successful **bench v2** — never from load-only smoke.
2. **Recipes auto-scaffold** after download — fix `scaffold_error` in code routing, don't hand-write YAML unless MoE/multimodal/DFlash/ds4/MTP needs it.
3. **Host-local git files:** `data/inference-profiles.yaml`, `data/inference-benchmarks.yaml` — skip-worktree; never reset without backup.
4. **LAN trust only** — mutation APIs on :80 have no auth; don't expose WAN-side.
5. **Inventory build** needs venv: `/opt/spark/venv/bin/python scripts/spark-inventory-build.py` (or `spark models inventory`).

## New model / golden audit

For onboarding weights through golden map + bench v2 + verify, read `docs/runbooks/new-model-golden-benchmark.md` in the repo (or use the `sparky-new-model-workflow` skill if installed).

Reports: `run/golden-audit-report.json` · map: `data/golden-recipes.yaml`

## Repo docs (read when stuck)

| Doc | Topic |
|-----|--------|
| `AGENTS.md` | Layout, rules, touchpoints |
| `docs/reference/spark-cli.md` | Full CLI |
| `docs/reference/inference-stack.md` | Gateway, recipes, architecture |
| `docs/runbooks/sparky-live-sync.md` | Pull code on live serving box |
| `install/INSTALL.md` | Install targets + modules |

## Code touchpoints (when patching SparkBench itself)

| Change | Where |
|--------|--------|
| Nginx routes | `install/common.sh` → `write_nginx_portal_site` |
| Inference logic | `scripts/spark-inference.py` (API reloads per request) |
| Inference API shell | `scripts/spark-inference-api.py` (needs restart if changed) |
| HF explore queue | `scripts/spark-hf.py` |
| Portal UI | `portal/index.html` |
