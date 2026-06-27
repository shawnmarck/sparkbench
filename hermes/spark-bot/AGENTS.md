# Spark agent — sparky homelab

## Host

| Item | Value |
|------|-------|
| Hostname | `sparky` (or `$SPARK_HOST`) |
| **Sparky repo** | `/opt/spark` — dashboard + Model Lab (SSH terminal cwd) |
| Hermes runtime | `/opt/hermes` — compose, agent data (**outside** `/opt/spark`) |
| Hermes data | `/opt/hermes/data/spark-bot/data` → container `/opt/data` |
| Scratch | `/opt/hermes/data/workspace` → sandbox `/workspace` |
| Hermes UI | `http://sparky:9119` |
| Sparky portal | `http://sparky/` (models UI, portal JSON) |

## Editing the dashboard

Terminal and file tools SSH to the host as `techno` with `cwd: /opt/spark` — full `spark` CLI and live repo edits. Refresh the browser to see static/portal updates.

SSH key setup (once, from techno — not via agent chat):

```bash
./setup-ssh-terminal.sh
```

Git on sparky is for checkpoints — not required for every tweak.

## Coexistence with Model Lab

- Inference stack lives at `/opt/spark` — **do not** start/stop models or kill the bench worker.
- Read-only inspection (`spark inference status`, log tails) is fine.
- Bench worker may own the GPU; cloud fallbacks (ZAI, OpenRouter) cover outages if inference is disturbed.
- Local inference wiring is Phase 5 (see `runbooks/phase-2-local-inference.md`).

## Interact (from techno)

```bash
spark-hermes              # CLI chat (primary terminal UI)
# Dashboard: http://sparky:9119
```

## Deploy (from techno)

```bash
cd ~/projects/sparky/hermes/scripts
./deploy-spark-bot.sh
./verify-spark-bot.sh
```

**First-time path split** (move Hermes out of `/opt/spark`):

```bash
# On sparky once, if /opt/hermes does not exist yet:
ssh sparky 'sudo mkdir -p /opt/hermes && sudo chown techno:techno /opt/hermes'

./migrate-hermes-out-of-spark.sh
```

Override runtime root: `SPARKY_HERMES_ROOT=~/hermes ./deploy-spark-bot.sh`

Secrets: `~/secure/sparky-hermes/spark-bot.env` (never in git).

## OAuth (Grok primary)

```bash
ssh sparky 'docker exec -it spark-bot hermes auth add xai-oauth --manual-paste'
```

Tokens persist in `/opt/hermes/data/spark-bot/data/auth.json`.

## Grok → Sparky (local inference)

### Recommended: use the `grok-sparky` wrapper (temp config)

Copy `scripts/grok-sparky` from this repo onto your client machine and put it in `$PATH` (e.g. `~/bin/grok-sparky`).

```bash
grok-sparky                  # starts Grok pointed at the current Sparky profile
grok-sparky "do the thing"   # headless + prompt
SPARKY_HOST=sparky grok-sparky
```

What it does:
- Fetches the current active profile name (exactly what you see in the inference UI).
- Builds a **temporary** config using `GROK_HOME=/tmp/grok-sparky.$$` (your permanent config is untouched).
- Creates two entries with safe ASCII keys derived from the real model + `name` set to a sanitized version of the actual profile name ("OpenCode - Qwen3.6 27B DFlash 262k" etc.). We sanitize special chars (· etc.) because they can cause blank entries or parsing problems in Grok's model picker.
- The picker will show the real Sparky model name (not "sparky").
- Gateway does the thinking/non-thinking switch based on the model id sent.
- Symlinks your data and cleans the temp dir after exit.

Re-run after profile switches.

### Manual / persistent alternative

If you prefer not using the wrapper, add these two entries to `~/.grok/config.toml`:

```toml
[model.sparky]
model = "sparky"
base_url = "http://sparky:9000/v1"
api_key = "local"
name = "Sparky (current profile)"
context_window = 262144

[model.sparky-think]
model = "sparky-think"
base_url = "http://sparky:9000/v1"
api_key = "local"
name = "Sparky (current profile, thinking)"
context_window = 262144
```

The gateway maps `model="sparky"` → normal and `model="sparky-think"` → thinking.

### Switching profiles

After `spark inference up <profile>`, just run `grok-sparky` again. It will pick up the new profile name from the inference status and give you clean entries matching the UI.

Active profile must expose Qwen tool-call flags (`--enable-auto-tool-choice`, `--tool-call-parser qwen3_xml`) when using Qwen-family models, or Grok agent turns fail with 400. See `docs/runbooks/new-model-golden-benchmark.md`.

Do **not** restart inference from Hermes chat unless explicitly asked.