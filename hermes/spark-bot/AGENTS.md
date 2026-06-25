# Spark agent — sparky homelab

## Host

| Item | Value |
|------|-------|
| Hostname | `sparky` |
| LAN | `192.168.0.101` |
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

When Model Lab has a profile loaded, point Grok at the gateway (not raw vLLM):

```toml
# ~/.grok/config.toml
[model.sparky-agentworld]
model = "qwen-agentworld-35b-a3b"   # must match active served_name
base_url = "http://sparky:9000/v1"
api_key = "local"
context_window = 256000
```

Active profile must expose Qwen tool-call flags (`--enable-auto-tool-choice`, `--tool-call-parser qwen3_xml`) or Grok agent turns fail with 400. See `docs/runbooks/new-model-golden-benchmark.md`.

Do **not** restart inference from Hermes chat unless explicitly asked.