# Sparky live sync — avoiding regressions

Three layers on the homelab. **Never treat sparky `/opt/spark` as a second dev clone.**

## Layers

| Layer | Where | What | Git pull on sparky? |
|-------|--------|------|---------------------|
| **Code** | techno → GitHub → sparky | `scripts/`, `recipes/`, `services/`, `portal/`, `docs/`, `hermes/` | Yes — via `./scripts/deploy-sparky.sh` |
| **Runtime data** | sparky only | `data/model-verification.yaml`, `inference-benchmarks.yaml`, `inference-profiles.yaml`, `model-catalog.yaml` | **No** — protected with `skip-worktree` |
| **Build/vendor** | sparky only | `vendor/`, `bin/llama-*`, `run/` | Ignored / local drift OK |

Runtime data is updated by **golden audit**, **bench v2**, **`spark models verify`**, and **`spark models inventory`** on sparky. Git copies are templates or stale snapshots — not the source of truth for the portal.

## One-time setup on sparky

```bash
cd /opt/spark
bash scripts/sparky-protect-runtime.sh
```

Deploy runs `sparky-protect-runtime.sh` automatically and **backs up runtime YAML before pull, restores after** — so git changes to those files on GitHub never clobber live audit results.

## Safe deploy (from techno)

```bash
./scripts/deploy-sparky.sh --status   # drift check first
./scripts/deploy-sparky.sh            # push + pull code paths only
```

Deploy will **not** stash untracked recipes, **not** overwrite skip-worktree runtime data, and **not** restart inference.

## What went wrong before

1. **Deploy stashed `-u`** — removed host-only recipe files (AgentWorld) not yet in git.
2. **Premature audit promote** — set `works` before bench v2 (fixed in `golden-inventory-audit.py`).
3. **Pull overwrote runtime data** — git `model-verification.yaml` replaced live golden-audit results.

## Export runtime data (optional)

When you want git to reflect a known-good sparky audit snapshot:

```bash
ssh sparky 'cd /opt/spark && git update-index --no-skip-worktree data/model-verification.yaml'
# copy or diff, commit on techno, re-protect on sparky
bash scripts/sparky-protect-runtime.sh
```

Default: leave runtime data on sparky only.

## Check live state

```bash
./scripts/deploy-sparky.sh --status
ssh sparky 'cd /opt/spark && git ls-files -v | grep "^S" && spark inference status | head -12'
```
