# Legacy CLI entry names (archived)

The homelab exposes a **single** command: `spark` (installed to `/usr/local/bin/spark`).

These names were previously on `PATH` as separate binaries. They remain as **implementation scripts** under `/opt/spark/scripts/` (called by `spark` internally). Do not add them back to `/usr/local/bin`.

## Migration

| Old command | New command |
|-------------|-------------|
| `spark-inference list` | `spark inference list` |
| `spark-inference status` | `spark inference status` |
| `spark-inference up <id>` | `spark inference up <id>` |
| `spark-inference down` | `spark inference down` |
| `spark-inference bench` | `spark inference bench` |
| `spark-inference recipe …` | `spark recipe …` |
| `spark-model-verify set …` | `spark models verify set …` |
| `spark-model-verify removal …` | `spark models removal …` |
| `spark-inventory-build` | `spark models inventory` |
| `spark-shelf-pull …` | `spark shelf pull …` |
| `spark-shelf-push …` | `spark shelf push …` |
| `spark-local-rm …` | `spark shelf rm …` |
| `spark-eugr …` | `spark engine eugr …` |
| `spark-llama …` | `spark engine llama …` |
| `spark-gpu-metrics` | `spark gpu` |
| `spark-hf-login` | `spark hf login` |

Shims in this folder (optional, not on PATH) print a deprecation hint and forward to `spark`.