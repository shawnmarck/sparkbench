# Sparky live sync — shared cookbook in git

Two ways to sync code with GitHub. **Recipes and GB10 perf data travel in git** so solo Spark clones inherit the cookbook.

| Path | Who | When |
|------|-----|------|
| **A — deploy from dev machine** | Local clone (`sparkbench`) | Default: commit → push → `./scripts/deploy-sparky.sh` |
| **B — git on spark host** | Agent on sparky | Pull when ready; commit maintainer cookbook updates back |

**Never treat sparky `/opt/spark` as a throwaway clone** — it runs inference. Local-only state stays on the box.

## Layers

| Layer | Git? | What | On `git pull` |
|-------|------|------|----------------|
| **Shared cookbook** | Yes — commit & push | `recipes/*.yaml`, `data/golden-recipes.yaml`, `data/model-catalog.yaml`, `data/model-verification.yaml`, `data/spark-explore-warnings.yaml` | **Update from origin** |
| **Code** | Yes | `scripts/`, `install/`, `services/`, `portal/`, `docs/` | Update |
| **Host-local** | skip-worktree on sparky | `data/inference-profiles.yaml`, `data/inference-benchmarks.yaml` | Keep sparky copy |
| **Host runtime** | gitignored | `run/*`, `logs/`, `portal/models.json`, `data/hf-*-queue.yaml`, legacy `data/inference-benchmark-history.yaml` | Never in git |
| **Host identity** | `/etc/spark/host.env` or `/opt/spark/host.env` (gitignored) | `SPARK_HOST`, `SPARK_LAN_IP`, `SPARK_USER` | Manual per box |
| **Secrets** | `/etc/spark/smb-credentials-models` | NAS CIFS credentials | Never in git |
| **Weights** | No | `/models/*` | Never in git |

### Headline vs matrix

| Store | Role |
|-------|------|
| `data/model-verification.yaml` | Portal **Spark** column: `works` / tok/s headline on this host |
| `recipes/*.yaml` → `context.bench_matrix` | **GB10 cookbook** perf grid (ctx ladder, kv sweep) for all clones |
| `run/inference-benchmark-history.yaml` | Full bench v2 session history (local, optional export) |

---

## One-time setup on sparky

```bash
cd /opt/spark
sudo bash install/spark-install bootstrap    # host.env + sudoers + portal base (once)
bash scripts/sparky-protect-runtime.sh       # skip-worktree on profiles/benchmarks only
bash scripts/migrate-host-local-data.sh      # move legacy data/ bench history → run/
```

Edit `/etc/spark/host.env` or `/opt/spark/host.env` if `SPARK_LAN_IP` or `SPARK_USER` differ from the example.

### Remote alignment

Maintainer box `/opt/spark` should track **`https://github.com/shawnmarck/sparkbench.git`**. Older installs may still have `origin` → `sparky-dashboard`; add sparkbench:

```bash
git remote add sparkbench https://github.com/shawnmarck/sparkbench.git 2>/dev/null || true
git fetch sparkbench main
```

Until history is fully merged, you can sync **code only**:

```bash
git fetch sparkbench main
git checkout sparkbench/main -- install/ scripts/sparky-protect-runtime.sh scripts/migrate-host-local-data.sh
```

---

## Pulling on a live box (checklist)

**Do not** run `sudo bash install/spark-install core` while inference is serving — it restarts APIs and rewrites nginx.

1. `spark inference status` — note active profile
2. `bash scripts/sparky-protect-runtime.sh` — clears wrong skip-worktree on catalog/verify
3. Stash or commit local recipe edits
4. `git pull --ff-only origin main` (or merge from `sparkbench/main` when aligned)
5. `bash scripts/migrate-host-local-data.sh`
6. `spark models inventory` if portal/catalog changed
7. **Skip** full `spark-install core` unless greenfield

Install-only update (safe while serving):

```bash
git fetch sparkbench main
git checkout sparkbench/main -- install/
bash install/spark-install list
```

---

## Path A — deploy from dev machine (default)

```bash
./scripts/deploy-sparky.sh --status
./scripts/deploy-sparky.sh
SKIP_PUSH=1 ./scripts/deploy-sparky.sh
```

Deploy stashes tracked code edits, pulls `origin/main`, restores **host-local** YAML only, runs `sparky-protect-runtime.sh` + `migrate-host-local-data.sh`.

---

## Path B — agent on sparky

```bash
cd /opt/spark
bash scripts/sparky-protect-runtime.sh
git fetch origin
git pull --ff-only origin main
bash scripts/migrate-host-local-data.sh
spark models inventory
```

### Host-local backup (profiles only)

```bash
cp data/inference-profiles.yaml /tmp/inference-profiles.yaml.bak
git pull --ff-only origin main
cp /tmp/inference-profiles.yaml.bak data/inference-profiles.yaml
bash scripts/sparky-protect-runtime.sh
```

---

## What went wrong before

1. **Deploy stashed `-u`** — removed host-only files not yet in git.
2. **Pull overwrote then restored stale verify/catalog** — fought the shared-cookbook model.
3. **skip-worktree on all `data/*.yaml`** — blocked pulling GB10 perf into clones.
4. **sparky `origin` pointed at old repo** — use `sparkbench` remote or repoint `origin`.

## Check live state

```bash
./scripts/deploy-sparky.sh --status
cd /opt/spark && git ls-files -v | grep '^S'
spark inference status | head -12
test -f /etc/spark/host.env && grep SPARK_LAN /etc/spark/host.env
```

Only `inference-profiles.yaml` and `inference-benchmarks.yaml` should show `S`. Warnings on catalog/verify mean run `sparky-protect-runtime.sh`.
