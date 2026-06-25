# spark-bot deployment runbook

## Dashboard

| Access | URL |
|--------|-----|
| LAN hostname | **http://sparky:9119** |
| LAN IP | **http://192.168.0.101:9119** |

**Login:** basic auth — username `techno`, password in `~/secure/sparky-hermes/dashboard-credentials.txt`.

Add to your homelab portal manually when ready.

## Runtime paths on sparky

Hermes runtime is **outside** the Sparky app repo so the agent can mount all of `/opt/spark` for dashboard edits.

```
/opt/hermes/                    # Hermes runtime (compose, agent state)
├── docker-compose.yml
└── data/
    ├── spark-bot/data/         → container /opt/data
    └── workspace/              → sandbox /workspace (scratch)

/opt/spark/                     # Sparky dashboard + Model Lab repo (agent cwd)
```

One-time on sparky if `/opt/hermes` does not exist:

```bash
sudo mkdir -p /opt/hermes && sudo chown techno:techno /opt/hermes
```

Migrating from legacy `/opt/spark/hermes`:

```bash
cd ~/projects/sparky/hermes/scripts
./migrate-hermes-out-of-spark.sh
```

## Prerequisites

- SSH: `ssh sparky` from techno (passwordless key)
- Docker on sparky
- Secrets at `~/secure/sparky-hermes/spark-bot.env`

### spark-bot.env template

```bash
GLM_API_KEY=your_zai_key
GLM_BASE_URL=https://api.z.ai/api/coding/paas/v4
OPENROUTER_API_KEY=sk-or-...   # optional fallback
```

Grok OAuth tokens go to `auth.json` on the data volume, not `.env`.

## SSH terminal (spark CLI on host)

One-time from techno — generates a dedicated key on sparky, installs pubkey in `authorized_keys`, switches terminal to SSH:

```bash
cd ~/projects/sparky/hermes/scripts
./setup-ssh-terminal.sh
```

Do **not** have Spark generate keys in chat (private key could land in session logs). Re-run after key loss; existing key is reused.

## Deploy

```bash
cd ~/projects/sparky/hermes/scripts
chmod +x *.sh
./deploy-spark-bot.sh
./verify-spark-bot.sh
```

`deploy-spark-bot.sh` will:

1. Render secrets to sparky
2. Sync compose, persona, config overlay
3. `docker compose pull && docker compose up -d --force-recreate spark-bot`

**Important:** use `--force-recreate` after `.env` changes — `docker restart` does not reload `env_file`.

## Grok OAuth (one-time)

Requires a TTY — plain `ssh host '...'` fails with "input device is not a TTY".

```bash
ssh -t sparky 'docker exec -it spark-bot hermes auth add xai-oauth --manual-paste'
```

Or from techno (same thing):

```bash
~/projects/sparky/hermes/scripts/oauth-grok.sh
```

Or two steps:

```bash
ssh -t sparky
docker exec -it spark-bot hermes auth add xai-oauth --manual-paste
```

1. Open the `accounts.x.ai` URL in your local browser
2. Sign in with SuperGrok account
3. Paste callback URL/code into the SSH session

Tokens persist at `/opt/hermes/data/spark-bot/data/auth.json`.

Runtime root: `/opt/hermes/`. Override with `SPARKY_HERMES_ROOT` in deploy scripts if needed.

## CLI chat (power user)

From techno:

```bash
spark-hermes                    # interactive TUI
spark-hermes -q "quick question"
spark-hermes shell              # bash in container
spark-hermes doctor
ssh spark-hermes                # same as shell (SSH config alias)
```

Script: `~/bin/spark-hermes` → `projects/sparky/hermes/scripts/spark-hermes`

## Backup to NAS

```bash
NAS_BACKUP_DEST=pollynas:/path/to/backups/sparky/hermes/spark-bot/ \
  ./backup-to-nas.sh
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Dashboard 502 | `ssh sparky 'docker logs spark-bot --tail 50'` |
| Grok 403 | OAuth quota — falls back to ZAI; re-auth with `--manual-paste` |
| Config not applied | Re-run `./deploy-spark-bot.sh` |
| Secrets stale | Re-run `./render-secrets.sh` then `force-recreate` |

## Model Lab

Do **not** run `spark inference` commands from this agent. See `phase-2-local-inference.md` for future local wiring.