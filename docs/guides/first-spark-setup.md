# First Spark setup (solo GB10)

One DGX Spark, one operator. Clone, install, browse the golden map, download a model, serve it.

## What you get from git

| In the repo | On your disk |
|-------------|----------------|
| `recipes/*.yaml` — launch config + GB10 bench matrix | `/models/<lab>/<slug>/` — weights (you download) |
| `data/golden-recipes.yaml` — model → golden profile | `portal/models.json` — built locally |
| `data/model-catalog.yaml` — HF repos, variants | |
| `data/model-verification.yaml` — headline tok/s / `works` | |

Git is the cookbook. Disk is the ingredients.

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

### 3. Host-local git protection

```bash
bash scripts/sparky-protect-runtime.sh
```

Keeps `data/inference-profiles.yaml` and `data/inference-benchmarks.yaml` local. Recipes and shared catalog data pull from git.

### 4. Build inventory

```bash
spark models inventory
```

Open **http://sparky/** → **Models**, or **http://sparky/models.html**. Catalog rows show `missing` until weights land.

### 5. Browse golden recipes (no weights required)

Golden models have a committed profile in `data/golden-recipes.yaml`. In the portal:

- Filter **Golden**
- Open a row → Model Lab shows recipe id, ctx ladder, KV sweep from git

Editor's pick on [sparkbench.dev](https://sparkbench.dev) is Ornith 1.5 (`ornith-ai/ornith-1.5-35b-a3b`). Everyday long-context Qwen is `opencode-qwen36-250k` (Qwen3.6-35B-A3B).

### 6. Download a golden model

**With NAS shelf** (another box already pushed backups):

```bash
spark shelf pull yuxinlu1/mellum2-12b-opus-thinking
```

**Without shelf** (Hugging Face):

```bash
spark models fetch yuxinlu1/mellum2-12b-opus-thinking
spark models fetch --dry-run nvidia/qwen3.6-35b-a3b   # preview
```

Or use **Download from HF** in the model detail pane. Mellum2 is a smaller first pull. Qwen3.6-35B-A3B NVFP4 is the everyday coding profile.

### 7. Run inference

```bash
spark inference list
spark inference up mellum2-12b-opus-q4
spark inference status
curl -s http://127.0.0.1:9000/v1/models | head
```

Clients should use model `sparky` on `http://sparky:9000/v1` so they follow the active profile.

### 8. Verify on your box (optional)

Upstream git may already include GB10 perf. To measure on **your** Spark:

```bash
spark models golden yuxinlu1/mellum2-12b-opus-thinking
# hours for long-ctx models — use nohup + --resume
```

See [new-model-golden-benchmark.md](../runbooks/new-model-golden-benchmark.md). Overnight sweeps: [benchmaster-agent.md](../runbooks/benchmaster-agent.md).

## Pull updates

```bash
cd /opt/spark
git pull origin main
spark models inventory
```

Deploy from a dev machine: `./scripts/deploy-sparky.sh` (see [sparky-live-sync](../runbooks/sparky-live-sync.md)).

**Do not** run `spark-install core` on a box that is serving.

## Further reading

| Doc | Topic |
|-----|--------|
| [installation-instructions.md](installation-instructions.md) | Full install + HTTP routes |
| [new-model-golden-benchmark.md](../runbooks/new-model-golden-benchmark.md) | Golden workflow |
| [spark-cli.md](../reference/spark-cli.md) | Full CLI |
| [model-shelf.md](model-shelf.md) | NAS layout (optional) |
| [model-picks.md](model-picks.md) | Why these models |
