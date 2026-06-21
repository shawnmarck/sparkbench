# /ops — inference orchestration (Phase 4 bake-off)

Operational installs for orchestrator UIs. Separate from the dashboard repo at `/opt/spark/`.

| Path | Purpose |
|------|---------|
| `/opt/spark/` | Portal, metrics, inventory, install scripts |
| `/ops/rookery/` | Rookery daemon + `config.toml` |
| `/ops/vllm-studio/` | vLLM Studio clone + `.env.local` |

## Bake-off URLs

| UI | URL | CLI |
|----|-----|-----|
| Open WebUI | http://sparky:3000 | docker |
| Rookery | http://sparky:3131 | `spark-rookery` |
| vLLM Studio | http://sparky:3080 | `spark-vllm-studio` |

Engines: `spark-eugr` (:8000), `spark-llama` (:8081). One GPU workload at a time.

Install: `sudo /opt/spark/install/18-ops-layout.sh` → `19-rookery.sh` → `17-vllm-studio.sh`
