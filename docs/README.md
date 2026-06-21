# Sparky Dashboard

Home lab portal and ops tooling for the DGX Spark (`sparky`) — live system dashboard, model inventory, inference helpers, and idempotent install scripts.

## Layout

```
/opt/spark/
├── README.md           -> symlink to docs/README.md
├── portal/             LAN portal shell (nginx, port 80)
│   ├── index.html      System dashboard + nav (Models / Chat / Netdata)
│   └── models.html     Model inventory view
├── scripts/            spark-gpu-metrics, inference, inventory, shelf tools
├── install/            Idempotent install scripts (run with sudo)
├── docs/               Documentation
├── services/           Docker compose / service configs
├── data/               model-catalog.yaml
└── vendor/
    └── spark-vllm-docker/   Upstream: https://github.com/eugr/spark-vllm-docker
```

Generated or local-only (not in git): `venv/`, `logs/`, `run/`, `portal/models.json`, `vendor/spark-vllm-docker/wheels/`.

## Network

| Item | Value |
|------|-------|
| Hostname | sparky |
| LAN IP | 192.168.0.101 (DHCP reservation) |

## Services

| Service | URL | Notes |
|---------|-----|-------|
| Portal | http://sparky/ | nginx → `/opt/spark/portal` |
| Metrics API | http://sparky/api/gpu | proxied to `spark-gpu-metrics` on :8765 |
| Netdata | http://sparky:19999 | System monitoring |
| Open WebUI | http://sparky:3000 | Chat (iframe in portal) |
| vLLM | http://sparky:8000 | Inference API |

## Install

Run install scripts **as the script path** (not `sudo bash …`) so the passwordless install sudo rule applies:

```bash
sudo /opt/spark/install/01-netdata-portal.sh
sudo /opt/spark/install/10-portal-gpu-widget.sh
```

Full install order: `00-grant-install-sudo.sh` (one-time) → `01` → shelf scripts `02`–`04` as needed → `10` for metrics widget.

## Model shelf (QNAP)

| Item | Value |
|------|-------|
| NAS IP | 192.168.0.99 |
| Share | models |
| Mount | /mnt/model-shelf |
| Credentials | `/etc/spark/smb-credentials-models` (root, 600) |

See `docs/MODEL-SHELF.md` and `install/02-model-shelf-mount.sh`.

## Changelog

- 2026-06-21: Portal shell with system metrics, sparklines, Docker/inference status
- 2026-06-21: Model inventory, shelf tooling, vLLM vendor integration
- 2026-06-21: Initial portal + Netdata install script