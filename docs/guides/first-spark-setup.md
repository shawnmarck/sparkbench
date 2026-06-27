# First Spark setup (solo GB10)

One DGX Spark (`sparky`), one operator. This guide gets you from clone to browsing golden recipes and downloading models.

## What you get from git

| In the repo | On your disk |
|-------------|----------------|
| `recipes/*.yaml` — launch config + GB10 bench matrix | `/models/<lab>/<slug>/` — weights (you download) |
| `data/golden-recipes.yaml` — which model → golden profile | `portal/models.json` — built locally |
| `data/model-catalog.yaml` — HF repos, variants | |
| `data/model-verification.yaml` — headline tok/s / `works` | |

**Git = cookbook. Disk = ingredients.**

## Checklist

### 1. Clone and install

```bash
git clone https://github.com/shawnmarck/sparkbench.git /opt/spark
cd /opt/spark
sudo bash install/spark-install bootstrap     # optional: passwordless re-runs
sudo bash install/spark-install core
sudo bash install/spark-install engine eugr   # or llama / ds4
sudo bash install/spark-install gateway
```

Optional NAS shelf: `sudo bash install/spark-install nas`.

### 2. Hugging Face login (for downloads)

```bash
spark hf login
```

### 3. Host-local git protection (on sparky)

```bash
bash scripts/sparky-protect-runtime.sh
```

Keeps `data/inference-profiles.yaml` local; **recipes and shared data pull from git**.

### 4. Build inventory

```bash
spark models inventory
```

Open **http://sparky/models.html** — all catalog models appear (status `missing` until downloaded).

### 5. Browse golden recipes (no weights required)

Golden models have a committed profile in `data/golden-recipes.yaml`. In the portal:

- Filter **Golden** (chip)
- Open detail → **Model Lab** shows recipe id, ctx ladder, KV sweep from git

### 6. Download a golden model

**With NAS shelf** (another Spark pushed backups):

```bash
spark shelf pull yuxinlu1/mellum2-12b-opus-thinking
```

**Without shelf** (HF — recommended for solo):

```bash
spark models fetch yuxinlu1/mellum2-12b-opus-thinking
spark models fetch --dry-run qwen/qwen-agentworld-35b-a3b   # preview
```

Or use **Download from HF** in the model detail pane.

### 7. Run inference

```bash
spark inference list
spark inference up mellum2-12b-opus-q4
spark inference status
curl -s http://127.0.0.1:9000/v1/models | head
```

### 8. Verify on your box (optional)

Upstream git may already include GB10 perf. To verify on **your** Spark:

```bash
spark models golden yuxinlu1/mellum2-12b-opus-thinking
# hours for long-ctx models — use nohup + --resume; see golden workflow runbook
```

## Pull updates

```bash
cd /opt/spark
git pull origin main
spark models inventory
```

Deploy from a dev machine: `./scripts/deploy-sparky.sh` (see [sparky-live-sync runbook](../runbooks/sparky-live-sync.md)).

## Further reading

| Doc | Topic |
|-----|--------|
| [new-model-golden-benchmark.md](../runbooks/new-model-golden-benchmark.md) | Golden workflow layers |
| [spark-cli.md](../reference/spark-cli.md) | Full CLI |
| [model-shelf.md](../guides/model-shelf.md) | NAS layout (optional) |
| [solo-user-backlog.md](../roadmap/solo-user-backlog.md) | Roadmap tasks |
