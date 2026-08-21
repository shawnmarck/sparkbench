# `spark` CLI — humans and agents

Single control command on the Spark box (`/usr/local/bin/spark`). Implementation lives in `/opt/spark/scripts/`. Only `spark` is on `PATH`.

| Audience | Start here |
|----------|------------|
| **Humans** | [Interactive use](#interactive-use-humans) |
| **Coding agents** | [Agent use](#agent-use-non-interactive) |
| **HTTP / gateway** | [APIs instead of CLI](#apis-instead-of-cli) |

Install: `sudo bash /opt/spark/install/spark-install core` (or `spark install core` after first core). See [install/INSTALL.md](../../install/INSTALL.md).

## Command shape

```text
spark <group> <subcommand> [args...]
```

| Group | Purpose |
|-------|---------|
| `status` | GPU + inference overview |
| `inference` | Profile switch (`up` / `down` / `bench`) |
| `recipe` | Model Lab lifecycle |
| `models` | Inventory, verify, fetch, golden workflow |
| `shelf` | Local disk ↔ NAS |
| `engine` | Low-level `eugr`, `llama`, or `ds4` |
| `gateway` | `:9000/v1` aliases and serve |
| `bench` | Per-recipe benchmark history |
| `benchmaster` | Overnight perf / intel queue |
| `gpu` | Metrics JSON |
| `hf` | Hugging Face login |
| `install` | Host bootstrap (sudo) |

Legacy names (`spark-inference`, `spark-eugr`, …) are not on `PATH`. See `scripts/legacy/README.md`.

## Interactive use (humans)

```bash
spark                      # top-level help
spark ?                    # same (zsh: see below)
spark inference help       # works in any shell
spark inference up help    # subcommand help + live profile list
spark inf help             # prefixes OK
```

**zsh:** unquoted `?` needs `/etc/zsh/zshrc.d/spark.zsh` (from `spark-install core`). Without it, use `help` or `spark inference '?'`.

**Tab completion:** bash `/etc/bash_completion.d/spark`, zsh `_spark`.

```bash
spark status
spark inference list
spark inference up opencode-qwen36-250k
spark inference bench
spark recipe list
spark models verify set nvidia/qwen3.6-35b-a3b works
spark shelf pull nvidia/qwen3.6-35b-a3b
spark engine eugr status
spark benchmaster status
```

Rules:

1. One GPU engine at a time.
2. Heavy switches take minutes. Check `spark inference status` before chatting.
3. `qwen36-nvfp4` is deprecated. Use `opencode-qwen36-250k` for Qwen3.6-35B-A3B.

## Agent use (non-interactive)

Treat `spark` as a scriptable ops API, not a REPL.

| Practice | Why |
|----------|-----|
| `spark <group> help` or `spark --help` | No `?` glob issues |
| `spark inference list` before `up` | Confirm the profile id |
| `spark inference status` before/after mutations | Verify the switch |
| Parse `spark gpu` JSON | Stable machine output |
| `/usr/local/bin/spark` if `PATH` is thin | cron, systemd, minimal env |
| Respect exit codes | Non-zero = failure |

```bash
spark inference list
spark inference up opencode-qwen36-250k
spark inference status
spark gpu

spark recipe list
spark recipe scaffold google/gemma-4-12b-it llamacpp
spark models verify set google/gemma-4-12b-it works
spark models inventory

spark models fetch yuxinlu1/mellum2-12b-opus-thinking --dry-run
spark models fetch yuxinlu1/mellum2-12b-opus-thinking
spark models golden yuxinlu1/mellum2-12b-opus-thinking

/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-golden-matrix-status.py

spark benchmaster status
spark benchmaster control pause
```

| Avoid | Use instead |
|-------|-------------|
| `spark inf ?` (unquoted `?`) | `spark inference help` |
| `spark-inference`, `spark-eugr`, … | `spark inference …`, `spark engine eugr …` |
| Assuming sudo for routine ops | sudo only for `install/*.sh` |
| Two engines | Status, then stop one |
| Blind `spark-install core` on a live box | `spark-install module …` |
| Manual `up` while Benchmaster is `running` | Pause the queue first |

### Suggested agent workflow

```text
1. spark inference status     → active profile? engines up?
2. spark benchmaster status   → is the queue holding the GPU?
3. spark inference list       → valid profile ids
4. spark inference up <id>    → switch if needed
5. poll status until ready (or GET /api/inference/status)
6. smoke / bench / user task
7. spark inference down       → when freeing the GPU
```

### Exit codes and output

- **stdout** — human tables or JSON (`spark gpu`)
- **stderr** — errors (`spark: …`)
- **`spark inference bench`** — minutes; give it a long timeout. Appends history.
- **`spark shelf push --background`** — returns immediately; poll `spark shelf push --status`

### Benchmark history

```bash
spark bench history <profile> [--json] [--limit N]
spark bench show <profile> <run_id> [--json]
spark bench note <profile> <run_id> "baseline before MTP tweak"
spark bench latest <profile> [--json]
```

HTTP: `GET /api/inference/benchmarks/<profile>/history`, `PATCH .../runs/<run_id>` with `{"note":"..."}`.

Default gate is bench v2. Site display prefers PBM 4k. See [benchmark-standard.md](benchmark-standard.md).

### Environment

| Variable | Default | Notes |
|----------|---------|-------|
| `SPARK_ROOT` | `/opt/spark` | Repo root |
| `HF_TOKEN` | — | Downloads / HF API. Never commit. |

Inventory uses `/opt/spark/venv/bin/python` via `spark models inventory`.

### Sudo (agents)

- Passwordless sudo for `install/*.sh` (`00-grant-install-sudo.sh`)
- Optional broader agent sudo: `07-grant-agent-sudo.sh`
- Inference API hot-reloads `spark-inference.py`. Restart only if `spark-inference-api.py` changed: `spark install restart inference-api`

## APIs instead of CLI

| Need | URL / command |
|------|-------------|
| GPU + inference probe | `GET http://sparky/api/gpu` or `spark gpu` |
| Active profile | `GET http://sparky/api/inference/status` (`?lite=1` for nav polls) |
| Switch / stop | `POST …/switch` · `POST …/down` |
| Bench (portal button) | `POST …/bench` → 202 async job |
| Bench history / notes | `GET …/benchmarks/<profile>/history` |
| Recipe lifecycle | `GET/POST …/recipes/*` |
| Log tail | `GET …/logs?profile=<id>` |
| OpenAI inference | `http://sparky:9000/v1/*` · `spark gateway --list-aliases` |
| Client activity | `GET http://sparky/api/activity` |
| Benchmaster | `GET/POST http://sparky/api/benchmaster/*` |
| Shelf | `GET http://sparky/api/shelf/status` |
| Portal inventory | `GET http://sparky/models.json` |

Internal: `127.0.0.1:8767` (inference API), `127.0.0.1:8769` (activity). Gateway switch policy: [inference-stack.md](inference-stack.md).

## `spark engine ds4`

DwarfStar native DeepSeek V4 Flash. Same port as eugr (**8000**). Mutually exclusive.

```bash
spark engine ds4 build    # spark-install engine ds4
spark engine ds4 up
spark engine ds4 status
spark engine ds4 down
spark engine ds4 logs
```

Pin: `data/ds4-dwarfstar.yaml`. Production profile: `antirez-deepseek-v4-flash-ds4`.

## Migration (old → new)

| Old | New |
|-----|-----|
| `spark-inference list` | `spark inference list` |
| `spark-inference recipe …` | `spark recipe …` |
| `spark-eugr up` | `spark engine eugr up` |
| `spark-llama status` | `spark engine llama status` |
| `spark-shelf-pull X` | `spark shelf pull X` |
| `spark-inventory-build` | `spark models inventory` |
| `spark-model-verify set …` | `spark models verify set …` |
| `spark-gpu-metrics` | `spark gpu` |
| `spark-hf-login` | `spark hf login` |

Full table: `scripts/legacy/README.md`
