# Spark Home Lab (`/opt/spark`)

DGX Spark homelab dashboard, model inventory, and inference tooling.

**Agents:** start with [`AGENT.md`](../AGENT.md).  
**Install index:** [`install/INSTALL.md`](../install/INSTALL.md).  
**Roadmap:** [`ROADMAP.md`](ROADMAP.md).

## Layout

```
/opt/spark/
├── AGENT.md              Agent + human quick start
├── README.md             → this file
├── portal/               LAN portal (nginx :80)
├── scripts/              spark-* CLIs and APIs
├── install/              Idempotent sudo scripts
├── data/                 model-catalog.yaml, model-verification.yaml
├── docs/                 Documentation
└── services/             Inference compose files
```

Staging copies may live in `~/spark` until install scripts promote to `/opt/spark`.

## Network

| Item | Value |
|------|-------|
| Hostname | sparky |
| LAN IP | 192.168.0.101 |
| WiFi | wlP9s9 |
| 10GbE | enP7s7 (when cabled) |

## Services (current)

| Service | URL | Notes |
|---------|-----|-------|
| Portal | http://sparky/ | System · Models · Chat · Netdata (optional nebula theme) |
| Models | http://sparky/models.html | Inventory + shelf ops |
| Metrics | http://sparky/api/gpu | `spark-gpu-metrics` |
| Netdata | http://sparky:19999/v3/ | Host metrics |
| vLLM (eugr) | http://sparky:8000/v1 | `spark-eugr` |
| llama.cpp | http://sparky:8081/v1 | `spark-llama` |
| Open WebUI | http://sparky:3000 | Chat UI |

## Model storage

| Path | Role |
|------|------|
| `/models` | Local workspace (4 TB NVMe) |
| `/mnt/model-shelf/models` | NAS mirror (SMB) |

See [`MODEL-SHELF.md`](MODEL-SHELF.md).

## Key commands

```bash
spark-eugr status              # vLLM NVFP4
spark-llama status             # llama.cpp GGUF
spark-shelf-push --all         # backup to NAS
spark-shelf-pull <path>        # fetch from NAS
spark-inventory-build          # portal/models.json
spark-hf-login                 # Hugging Face token
```

Downloads: `scripts/spark-download-models.sh` (batch), `scripts/spark-download-gemma4.sh` (Gemma 4 add-on).

## Portal theme (Theme B)

Optional DGX OOBE-style nebula canvas on **System** and **Models**. Toggle via the constellation icon in the top nav; preference persists in `localStorage` (`sparky-theme`). Add `?theme=b` to URL to opt in on first visit.

| Path | Role |
|------|------|
| `portal/assets/sparky-theme.js` | Toggle, live theme switch, parent/iframe sync |
| `portal/assets/oobe-nebula.js` | Canvas particle animation |
| `portal/assets/nebula-tune.js` | Dev tuning panel (gear icon, bottom-left) |
| `portal/themes/theme-b.css` | Nebula layout + frosted cards |
| `portal/themes/theme-ui.css` | Toggle + tune panel styles |

Default theme (navy) is unchanged when Theme B is off. Bake-off nav links (Rookery, Studio) removed from portal.

## Install / update

```bash
cd /opt/spark   # or ~/spark staging
sudo bash install/<script>.sh
```

Core stack: `02` → `03` → `04` → `05` → `10` → `11` → `12`.  
Inference: `16-eugr-vllm-qwen36.sh`, `13-llama-cpp-smoke.sh` (one engine at a time).  
## Documentation map

| Doc | Topic |
|-----|-------|
| `ROADMAP.md` | Phases and status |
| `INFERENCE-STACK.md` | Phase 5 inference control plane spec |
| `INFERENCE-SMOKE.md` | eugr vLLM smoke |
| `LLAMACPP-SMOKE.md` | llama.cpp smoke |
| `MODEL-SHELF.md` | Shelf layout + sync |
| `MODEL-PICKS-REPORT.md` | Why each model was downloaded |

## NAS credentials

| Item | Value |
|------|-------|
| NAS | 192.168.0.99 |
| Share | `models` |
| Mount | `/mnt/model-shelf` |
| Creds file | `/etc/spark/smb-credentials-models` (root, 600) |

## Changelog

- 2026-06-21: Theme B nebula portal skin (System + Models), iframe theme sync, tuned defaults; bake-off UIs removed (Rookery, vLLM Studio); Phase 5 `INFERENCE-STACK.md` + `recipes/` scaffold; inference-profiles.yaml
- 2026-06-21: AGENT.md, install renumber, nginx common helper, network tile, model inventory chips
- 2026-06-21: Shelf API, Spark verify, queued removal, llama.cpp + Gemma 4 catalog
- 2026-06-21: Initial portal + Netdata