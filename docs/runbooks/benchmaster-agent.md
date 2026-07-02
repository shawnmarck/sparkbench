# Benchmaster agent — tmux + OpenCode on Sparky

Long-lived conversational control for the Benchmaster queue. The **systemd worker** runs jobs; **you (or OpenCode)** supervise via HTTP/CLI.

Skill reference: `.claude/skills/benchmaster/SKILL.md`

---

## Bootstrap

```bash
ssh sparky
cd /opt/spark

# Ensure API is up
curl -fsS http://127.0.0.1/api/benchmaster/status | python3 -m json.tool

# Persistent session
tmux new -s benchmaster
```

Inside tmux:

```bash
cd /opt/spark
opencode    # or cursor-agent — your supervisor LLM, not the model under test
```

Detach: `Ctrl-b d` · Reattach: `tmux attach -t benchmaster`

Install API if missing:

```bash
sudo bash install/spark-install module core/benchmaster-api.sh
sudo systemctl enable --now spark-benchmaster-api.service
```

Queue defaults to **paused** after install. Resume when ready:

```bash
spark benchmaster control resume
# or
curl -s -X POST http://sparky/api/benchmaster/control \
  -H 'Content-Type: application/json' -d '{"action":"resume"}'
```

---

## What to tell the agent

Examples that map to real tools (not improvised shell):

| Prompt | Agent should |
|--------|----------------|
| "What's in the bench queue?" | `GET /api/benchmaster/queue` or `spark benchmaster queue` |
| "Pause after the current job" | `control stop_after_current` |
| "Abort and requeue at front" | `control abort_current_requeue_front` |
| "Queue ornith FP8 perf sweep" | `queue/add` with `perf_sweep` + profile + inventory |
| "Why did FP8 fail?" | Read `run/benchmaster/runs/<id>/summary.json` + phase logs |
| "Is GPU free for intel?" | `GET /api/benchmaster/jobs/available` |
| "Tail live progress" | `tail -F logs/benchmaster.log` or SSE `/api/benchmaster/stream` |

---

## Split-pane layout (optional)

```bash
tmux new -s benchmaster
# pane 0: opencode
# Ctrl-b "  split horizontal
# pane 1:
tail -F /opt/spark/logs/benchmaster.log
```

Or watch portal: `http://sparky/#benchmaster`

---

## OpenCode vs model-under-test

| Role | Endpoint |
|------|----------|
| **Supervisor** (OpenCode's model) | Cloud or local — whatever you configure in OpenCode |
| **Model under test** (intel / chat) | `http://sparky:9000/v1` gateway during intel_eval |

Do not point OpenCode at the same profile you're benchmarking unless intentional.

---

## Overnight `/loop` babysit (manual pattern)

Until Phase 3b automation ships, poll from a second tmux pane or cron on sparky:

```bash
while sleep 900; do
  st=$(curl -fsS http://127.0.0.1/api/benchmaster/status)
  echo "$(date -Is) $st" | tee -a /opt/spark/logs/benchmaster-babysit.log
  echo "$st" | python3 -c "
import sys,json
d=json.load(sys.stdin)
j=d.get('current_job') or {}
if d.get('counts',{}).get('failed'):
    print('ALERT: failed jobs', d['counts'])
if j.get('state')=='running':
    print('running', j.get('id'), (j.get('progress') or {}).get('message'))
"
done
```

Watch stdout for `AGENT_BENCHMASTER_EVENT` if tailing `journalctl -u spark-benchmaster-api -f`.

---

## Remote intel worker (Mac/techno)

Not in tmux on Sparky — runs on Docker host:

```bash
# Mac
cp /path/to/spark/install/worker.yaml.example ~/.config/sparkbench/worker.yaml
# edit spark_base + worker_id

python3 spark-benchmaster-worker.py loop
```

Tailscale smoke:

```bash
curl -fsS http://sparky.vimba-turtle.ts.net/api/benchmaster/status
curl -fsS http://sparky.vimba-turtle.ts.net:9000/v1/models
```

---

## After code pull on live box

```bash
sudo systemctl restart spark-benchmaster-api.service
```

Do **not** run `spark-install core` on a serving box — use module restart above.

See also: `docs/runbooks/sparky-live-sync.md`
