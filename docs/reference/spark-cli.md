# `spark` CLI — humans and agents

Single homelab control command on **sparky** (`/usr/local/bin/spark`). Implementation lives in `/opt/spark/scripts/`; only `spark` is on `PATH`.

| Audience | Start here |
|----------|------------|
| **Humans** (interactive shell) | [Interactive use](#interactive-use-humans) |
| **Coding agents** (Cursor, Hermes, scripts) | [Agent use](#agent-use-non-interactive) |
| **HTTP / gateway** (no shell) | [APIs instead of CLI](#apis-instead-of-cli) |

Install once: `sudo bash /opt/spark/install/20-spark-cli.sh` (also chained from `install/17-inference-api.sh`).

---

## Command shape

```text
spark <group> <subcommand> [args...]
```

| Group | Purpose |
|-------|---------|
| `status` | GPU + inference overview |
| `inference` | Profile switch (`up` / `down` / `bench`) |
| `bench` | Per-recipe benchmark **history** (read/write notes) |
| `recipe` | Model Lab lifecycle |
| `models` | Inventory verify / removal / rebuild |
| `shelf` | Local disk ↔ NAS |
| `engine` | Low-level `eugr`, `llama`, or `ds4` (bypass profile switcher) |
| `gpu` | Metrics JSON |
| `hf` | Hugging Face login |

Legacy names (`spark-inference`, `spark-eugr`, …) are **not** on `PATH`. See `scripts/legacy/README.md`.

---

## Interactive use (humans)

### Discover commands

```bash
spark                      # top-level help
spark ?                    # same (zsh: see below)
spark inference help       # group help — works in any shell
spark inference up help    # subcommand help + live profile list
spark inf help             # prefixes OK
```

**zsh:** unquoted `?` needs `/etc/zsh/zshrc.d/spark.zsh` (from `install/20`). Without it, use `help` or `spark inference '?'`.

**Tab completion:** bash `/etc/bash_completion.d/spark`, zsh `_spark`. Prefixes work: `spark inf<TAB>` → `inference`.

### Everyday examples

```bash
spark status
spark inference list
spark inference up qwen36-nvfp4
spark inference bench
spark recipe list
spark models verify set google/gemma-4-12b-it works
spark shelf pull nvidia/qwen3.6-35b-a3b
spark engine eugr status
```

### Rules

1. **One GPU engine at a time** — `spark engine eugr down` before `spark engine llama up`.
2. Heavy profile switches take minutes; check `spark inference status` before chatting.

---

## Agent use (non-interactive)

Agents should treat `spark` as a **scriptable ops API**, not an interactive REPL.

### Do

| Practice | Why |
|----------|-----|
| Use `spark <group> help` or `spark --help` | Shell-safe discovery (no `?` glob issues) |
| Run `spark inference list` before `up` | Confirms profile id exists |
| Run `spark inference status` before/after mutations | Verifies switch outcome |
| Parse JSON from `spark gpu` | Stable machine output |
| Use full path if `PATH` is thin: `/usr/local/bin/spark` | Works in cron, systemd, minimal env |
| Respect exit codes | Non-zero = failure; read stderr |

```bash
# Discover profiles (parse first column after header rule)
spark inference list

# Switch profile (evicts current engine if needed)
spark inference up qwen36-nvfp4

# Confirm
spark inference status

# Metrics JSON
spark gpu

# Model Lab
spark recipe list
spark recipe scaffold google/gemma-4-12b-it llamacpp
spark models verify set google/gemma-4-12b-it works
spark models inventory
```

### Don't

| Avoid | Use instead |
|-------|-------------|
| `spark inf ?` (unquoted `?`) | `spark inference help` or `spark inference list` |
| Legacy `spark-inference`, `spark-eugr`, … | `spark inference …`, `spark engine eugr …` |
| Assuming sudo for routine ops | `spark` mutates via scripts; sudo only for `install/*.sh` |
| Running two engines | Check status; stop one before starting another |
| Blind `install/05` re-runs | Prefer targeted install scripts |

### Suggested agent workflow

```text
1. spark inference status     → active profile? engines up?
2. spark inference list       → valid profile ids
3. spark inference up <id>    → switch (if needed)
4. poll spark inference status until ready (or HTTP /api/inference/status)
5. run smoke / bench / user task
6. spark inference down       → when freeing GPU for another profile
```

### Exit codes and output

- **stdout** — human tables or JSON (`spark gpu`); suitable for parsing where documented.
- **stderr** — errors (`spark: …`).
- **`spark inference bench`** — can take minutes; run with adequate timeout. Appends to per-recipe history; does not change start/poll semantics.
- **`spark shelf push --background`** — returns immediately; poll `spark shelf push --status` or shelf API.

### Benchmark history (read/write notes)

```bash
spark bench history <profile> [--json] [--limit N]
spark bench show <profile> <run_id> [--json]
spark bench note <profile> <run_id> "baseline before MTP tweak"
spark bench latest <profile> [--json]
```

HTTP: `GET /api/inference/benchmarks/<profile>/history`, `PATCH .../runs/<run_id>` with `{"note":"..."}`.

**Benchmark standard:** see [benchmark-standard.md](benchmark-standard.md) — default `BENCH_STANDARD=v2`.

Cards and Inference tab still show **latest** `tok_s`; full timeline is in history + Models detail panel.

### Environment

| Variable | Default | Notes |
|----------|---------|-------|
| `SPARK_ROOT` | `/opt/spark` | Repo root |
| `HF_TOKEN` | — | Downloads / HF API (never commit) |

Inventory build uses venv: `/opt/spark/venv/bin/python` (invoked internally by `spark models inventory`).

### Sudo (agents)

- Passwordless sudo for `install/*.sh` only (`00-grant-install-sudo.sh`).
- Optional broader agent sudo: `07-grant-agent-sudo.sh`.
- Inference API code hot-reloads — usually **no** `systemctl restart` after editing `spark-inference.py`; hit `/api/inference/*` or use `install/19-inference-api-restart.sh` if stuck.

---

## APIs instead of CLI

Prefer HTTP when the agent has no shell or needs JSON without parsing tables:

| Need | URL / command |
|------|-------------|
| GPU + inference probe | `GET http://sparky/api/gpu` or `spark gpu` |
| Active profile | `GET http://sparky/api/inference/status` (`?lite=1` for nav polls) |
| Switch / stop profile | `POST http://sparky/api/inference/switch` · `POST …/down` |
| **Benchmark (portal button)** | `POST http://sparky/api/inference/bench` → 202 async job |
| Bench history / notes | `GET …/benchmarks/<profile>/history` · `PATCH …/runs/<run_id>` |
| Recipe lifecycle | `GET/POST http://sparky/api/inference/recipes/*` (scaffold, testing, promote) |
| Log tail | `GET http://sparky/api/inference/logs?profile=<id>` |
| **OpenAI inference (stable)** | `GET/POST http://sparky:9000/v1/*` · `spark gateway --list-aliases` |
| Shelf job status | `GET http://sparky/api/shelf/status` or `spark shelf status` |
| Portal inventory | `GET http://sparky/models.json` (after `spark models inventory`) |

Internal listener: `127.0.0.1:8767` (`spark-inference-api.service`). Portal nginx proxies `/api/inference/*` to it.

Gateway/agents mapping many model names → one profile: see `docs/reference/inference-stack.md` (503 + retry during cold start).

---

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
### `spark engine ds4`

DwarfStar native DeepSeek V4 Flash (`ds4-server`). Same port as eugr (**8000**) — mutually exclusive.

```bash
spark engine ds4 build    # cuda-spark (install/22)
spark engine ds4 up
spark engine ds4 status
spark engine ds4 down
spark engine ds4 logs
```

Pin: `data/ds4-dwarfstar.yaml`. Production profile: `antirez-deepseek-v4-flash-ds4`.

.