# Spark Home Lab (`/opt/spark`)

Organized services and docs for the DGX Spark (sparky).

## Layout

```
/opt/spark/
├── README.md           -> symlink to docs/README.md
├── portal/             Static LAN portal (nginx)
│   └── index.html
├── docs/               This documentation
├── install/            Idempotent install scripts (run with sudo)
│   └── 01-netdata-portal.sh
└── services/           Future: inference, cache, sync configs
```

Staging copies live in `~/spark/` until install scripts promote them to `/opt/spark`.

## Network

| Item | Value |
|------|-------|
| Hostname | sparky |
| LAN IP | 192.168.0.101 (DHCP reservation) |
| WiFi iface | wlP9s9 |

## Services

| Service | URL | Port | Status |
|---------|-----|------|--------|
| Portal | http://sparky/ | 80 | after install |
| Netdata | http://sparky:19999 | 19999 | after install |

## Install / update

From sparky (requires sudo password once):

```bash
sudo bash ~/spark/install/01-netdata-portal.sh
```

## What is NOT installed yet

- Tailscale / remote VPN
- Inference stacks (vLLM, llama.cpp)
- Inference UIs (vLLM Studio, Rookery)
- QNAP model shelf mount

See `~/spark/docs/ROADMAP.md` for planned phases.

## Changelog

- 2026-06-21: Shelf push `--background`/`--bwlimit`, `spark-hf-login`, llama.cpp smoke (install 11)

- 2026-06-21: Initial portal + Netdata install script

## Model shelf (QNAP)

| Item | Value |
|------|-------|
| NAS IP | 192.168.0.99 |
| Share | models |
| Mount | /mnt/model-shelf |
| Protocol | SMB/CIFS (NFS not enabled on NAS) |
| Credentials | /etc/spark/smb-credentials-models (root, 600) |

Install:
```bash
# one-time credentials (replace password)
sudo install -m 600 /dev/stdin /etc/spark/smb-credentials-models <<EOF
username=shawn
password=YOUR_PASSWORD
domain=WORKGROUP
