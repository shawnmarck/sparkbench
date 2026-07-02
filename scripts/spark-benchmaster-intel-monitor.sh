#!/usr/bin/env bash
# Poll intel_eval job until done/failed or timeout. Logs to logs/benchmaster-intel-monitor.log
set -euo pipefail
ROOT="${SPARK_ROOT:-/opt/spark}"
JOB_ID="${1:-}"
MAX_WAIT_S="${2:-14400}"
LOG="${ROOT}/logs/benchmaster-intel-monitor.log"
API="http://127.0.0.1/api/benchmaster"

mkdir -p "${ROOT}/logs"
log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

if [[ -z "$JOB_ID" ]]; then
  JOB_ID=$(curl -fsS "${API}/jobs/available" | python3 -c "
import json,sys
d=json.load(sys.stdin)
jobs=d.get('jobs') or []
print(jobs[0]['id'] if jobs else '')
" 2>/dev/null || true)
fi

if [[ -z "$JOB_ID" ]]; then
  JOB_ID=$(curl -fsS "${API}/status" | python3 -c "
import json,sys
d=json.load(sys.stdin)
j=d.get('current_job') or {}
print(j.get('id') or '')
" 2>/dev/null || true)
fi

[[ -n "$JOB_ID" ]] || { log "no job id to monitor"; exit 1; }

log "monitoring intel job ${JOB_ID} (max ${MAX_WAIT_S}s)"
deadline=$(( $(date +%s) + MAX_WAIT_S ))
last_msg=""

while [[ $(date +%s) -lt $deadline ]]; do
  st=$(curl -fsS "${API}/status")
  state=$(echo "$st" | python3 -c "
import json,sys
d=json.load(sys.stdin)
j=d.get('current_job') or {}
if j.get('id') != '${JOB_ID}':
    # maybe finished — check queue
    import urllib.request
    q=json.loads(urllib.request.urlopen('${API}/queue').read())
    for it in q.get('items') or []:
        if it.get('id')=='${JOB_ID}':
            print(it.get('state','?'))
            raise SystemExit(0)
    print('gone')
else:
    p=j.get('progress') or {}
    pr=j.get('prereq') or {}
    print(j.get('state','?'), p.get('phase',''), p.get('message',''), pr.get('status',''))
" 2>/dev/null || echo "error")

  if [[ "$state" != "$last_msg" ]]; then
    log "status: $state"
    last_msg="$state"
  fi

  prog="${ROOT}/run/benchmaster/runs/${JOB_ID}/intel-progress.json"
  if [[ -f "$prog" ]]; then
    cmd=$(python3 -c "import json; d=json.load(open('$prog')); print(d.get('harbor_cmd','')[:200])" 2>/dev/null || true)
    [[ -n "$cmd" && "$cmd" != *"logged"* ]] && log "harbor_cmd: $cmd" && touch "${ROOT}/run/benchmaster/runs/${JOB_ID}/.cmd_logged" 2>/dev/null || true
  fi

  if [[ "$state" == "done" || "$state" == "failed" || "$state" == "gone" ]]; then
    log "finished state=$state"
    curl -fsS "${API}/runs/${JOB_ID}" 2>/dev/null | python3 -m json.tool >> "$LOG" 2>&1 || true
    exit 0
  fi
  sleep 30
done

log "monitor timeout"
exit 1
