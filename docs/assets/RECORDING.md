# Recording demo assets

SparkBench ships one portal GIF in the repo. CLI and install recordings convert better on launch — capture these on a real Spark box.

## Portal (done)

`docs/assets/sparkbench-demo.gif` — Inference, Models, and Explore tabs. Re-record when the UI changes materially.

## CLI session (recommended)

Record switching a profile and running bench v2:

```bash
asciinema rec -t sparkbench-cli.cast
spark status
spark inference list
spark inference up qwen36-nvfp4    # or any enabled profile
spark inference status
spark inference bench
spark inference status
# Ctrl+D to finish
```

Export GIF (requires [agg](https://github.com/asciinema/agg)):

```bash
agg sparkbench-cli.cast docs/assets/sparkbench-cli.gif
```

Commit the `.cast` and/or `.gif` and reference from README.

## Install + first benchmark (recommended)

```bash
asciinema rec -t sparkbench-install.cast
curl -fsSL https://raw.githubusercontent.com/shawnmarck/sparkbench/main/scripts/bootstrap-sparkbench.sh | sudo bash
sudo bash install/spark-install engine eugr
spark inference list
spark inference up <profile>
spark inference bench
```

Or use Loom/OBS — same story: **bootstrap → engine → up → bench**.

## Before / after framing

| Without SparkBench | With SparkBench |
|--------------------|-----------------|
| Manual docker compose per model | `spark inference up <profile>` |
| Ad-hoc curl benchmarks | `spark inference bench` (bench v2 standard) |
| HF download scripts | Explore queue + auto-scaffold |
| No shared leaderboard data | Results feed [sparkbench.dev](https://sparkbench.dev) |

Use this table in README or X posts until video is ready.
