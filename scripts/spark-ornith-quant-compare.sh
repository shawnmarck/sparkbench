#!/usr/bin/env bash
# Ornith-1.0-35B MoE quant A/B: Q8_0 GGUF (baseline) vs FP8 vs ModelOpt NVFP4 (eugr).
# Downloads weights, scaffolds recipes, runs bench-agent-v2 on each at 262k ctx (~50k fill).
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
PY="${ROOT}/venv/bin/python3"
LOG="${ROOT}/logs/ornith-quant-compare.log"
PID_FILE="${ROOT}/run/ornith-quant-compare.pid"
MODEL_ROOT="/models/deepreinforce-ai/ornith-1.0-35b"
HF="${HF_BIN:-hf}"

INV="deepreinforce-ai/ornith-1.0-35b"
BASELINE_PROF="deepreinforce-ai-ornith-1-0-35b-llama"
FP8_PROF="deepreinforce-ai-ornith-1-0-35b-fp8-eugr"
NVFP4_PROF="deepreinforce-ai-ornith-1-0-35b-nvfp4-eugr"

FP8_REPO="deepreinforce-ai/Ornith-1.0-35B-FP8"
NVFP4_REPO="LS-ML/Ornith-1.0-35B-ModelOpt-NVFP4-Expert"

mkdir -p "${ROOT}/logs" "${ROOT}/run"
echo $$ >"$PID_FILE"

log() { echo "[$(date -Is)] ornith-ab: $*" | tee -a "$LOG"; }

wait_stable_dir() {
  local dir=$1 label=$2
  log "waiting for ${label} download in ${dir}"
  while true; do
    if pgrep -f "hf download.*${label}" >/dev/null 2>&1; then
      sleep 45
      continue
    fi
    if [[ -f "${dir}/config.json" ]] && compgen -G "${dir}/*.safetensors" >/dev/null 2>&1; then
      local s1 s2
      s1=$(du -sb "$dir" 2>/dev/null | awk '{print $1}')
      sleep 60
      s2=$(du -sb "$dir" 2>/dev/null | awk '{print $1}')
      if [[ "$s1" == "$s2" && "$s2" -gt 1000000000 ]]; then
        log "${label} stable size=$(( s2 / 1024 / 1024 / 1024 ))GiB"
        return 0
      fi
    fi
    sleep 30
  done
}

ensure_model_dirs() {
  if mkdir -p "${MODEL_ROOT}/fp8" "${MODEL_ROOT}/nvfp4" 2>/dev/null; then
    return 0
  fi
  log "need sudo to create ${MODEL_ROOT}/{fp8,nvfp4}"
  log "run: sudo mkdir -p ${MODEL_ROOT}/{fp8,nvfp4} && sudo chown -R \$USER:${MODEL_ROOT##*/} ${MODEL_ROOT}/fp8 ${MODEL_ROOT}/nvfp4"
  return 1
}

start_downloads() {
  ensure_model_dirs || return 1
  if [[ ! -f "${MODEL_ROOT}/fp8/config.json" ]]; then
    log "starting FP8 download -> ${MODEL_ROOT}/fp8"
    nohup "$HF" download "$FP8_REPO" --local-dir "${MODEL_ROOT}/fp8" >>"$LOG" 2>&1 &
  else
    log "FP8 dir already present"
  fi
  if [[ ! -f "${MODEL_ROOT}/nvfp4/config.json" ]]; then
    log "starting NVFP4 download -> ${MODEL_ROOT}/nvfp4"
    nohup "$HF" download "$NVFP4_REPO" --local-dir "${MODEL_ROOT}/nvfp4" >>"$LOG" 2>&1 &
  else
    log "NVFP4 dir already present"
  fi
}

write_services_and_recipes() {
  log "writing eugr services + draft recipes"
  "$PY" - <<'PY'
from pathlib import Path
import yaml
from datetime import datetime, timezone

ROOT = Path("/opt/spark")
SERVICES = ROOT / "services"
RECIPES = ROOT / "recipes" / "drafts"
MODEL_ROOT = Path("/models/deepreinforce-ai/ornith-1.0-35b")

COMMON_PARSERS = """    --enable-auto-tool-choice \\
    --tool-call-parser qwen3_xml \\
    --reasoning-parser qwen3 \\
"""

def eugr_service(profile_id, model_dir, served_name, weight_format):
    moe = "    --moe-backend marlin \\\n" if weight_format == "nvfp4" else ""
    env = """
env:
  VLLM_MARLIN_USE_ATOMIC_ADD: "1"
""" if weight_format == "nvfp4" else ""
    load_fmt = "fastsafetensors" if weight_format == "nvfp4" else "auto"
    gpu = 0.80 if weight_format == "nvfp4" else 0.85
    batched = 16384 if weight_format == "nvfp4" else 32768
    attn = "    --attention-backend flashinfer \\\n" if weight_format == "nvfp4" else ""
    return f"""# Ornith 35B MoE eugr ({weight_format}) — A/B compare
recipe_version: "1"
name: {profile_id}
description: eugr vLLM serve Ornith-1.0-35B {weight_format}

model: {served_name}
container: vllm-node
{env}
defaults:
  port: 8000
  host: 0.0.0.0
  tensor_parallel: 1
  gpu_memory_utilization: {gpu}
  max_model_len: 262144
  max_num_seqs: 4
  max_num_batched_tokens: {batched}

command: |
  vllm serve {model_dir} \\
    --host {{host}} \\
    --port {{port}} \\
    --served-model-name {served_name} \\
    --tensor-parallel-size {{tensor_parallel}} \\
    --trust-remote-code \\
{COMMON_PARSERS}    --kv-cache-dtype auto \\
{attn}{moe}    --gpu-memory-utilization {{gpu_memory_utilization}} \\
    --max-model-len {{max_model_len}} \\
    --max-num-seqs {{max_num_seqs}} \\
    --max-num-batched-tokens {{max_num_batched_tokens}} \\
    --enable-chunked-prefill \\
    --enable-prefix-caching \\
    --load-format {load_fmt}
"""

def recipe(profile_id, name, eugr_path, tag):
    return {
        "id": profile_id,
        "name": name,
        "inventory_path": "deepreinforce-ai/ornith-1.0-35b",
        "engine": "eugr",
        "tier": "heavy",
        "lifecycle": "draft",
        "served_name": profile_id.replace("-eugr", "").replace("deepreinforce-ai-ornith-1-0-35b", "ornith-1.0-35b"),
        "port": 8000,
        "tags": ["lab", "eugr", "ornith", tag],
        "notes": (
            f"Ornith 35B MoE A/B compare ({tag}). Scaffolded {datetime.now(timezone.utc).date().isoformat()}. "
            "Same bench cell as Q8_0 golden: 262k ctx, ~50k fill, bench-agent-v2."
        ),
        "eugr_recipe": str(eugr_path),
        "context": {
            "default": 262144,
            "native": 262144,
            "kv_default": "fp8" if tag != "q8-gguf" else "q8_0",
            "presets": {
                "golden": {"label": "Golden compare", "ctx": 262144, "kv": "fp8" if tag != "q8-gguf" else "q8_0"},
            },
        },
    }

specs = [
    ("deepreinforce-ai-ornith-1-0-35b-fp8-eugr", "ornith-1.0-35b FP8 (eugr)", MODEL_ROOT / "fp8", "fp8", "fp8"),
    ("deepreinforce-ai-ornith-1-0-35b-nvfp4-eugr", "ornith-1.0-35b NVFP4 (eugr)", MODEL_ROOT / "nvfp4", "nvfp4", "nvfp4"),
]
for pid, name, mdir, wf, tag in specs:
    svc = SERVICES / f"eugr-{pid}.yaml"
    svc.write_text(eugr_service(pid, mdir, f"ornith-1.0-35b-{tag}", wf))
    rec_path = RECIPES / f"{pid}.yaml"
    rec_path.write_text(yaml.safe_dump(recipe(pid, name, svc, tag), sort_keys=False, default_flow_style=False))
    print("wrote", svc.name, rec_path.name)
PY
}

update_bench_context() {
  "$PY" - <<'PY'
from pathlib import Path
import yaml

path = Path("/opt/spark/data/profile-bench-context.yaml")
data = yaml.safe_load(path.read_text()) or {}
profiles = data.setdefault("profiles", {})
for pid in (
    "deepreinforce-ai-ornith-1-0-35b-fp8-eugr",
    "deepreinforce-ai-ornith-1-0-35b-nvfp4-eugr",
):
    profiles[pid] = {"ctx": 262144}
path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
print("updated profile-bench-context for ornith eugr A/B")
PY
}

wait_gpu_idle() {
  while pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-inference\.py bench' >/dev/null 2>&1 \
     || pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-golden-workflow\.py' >/dev/null 2>&1; do
    sleep 30
  done
}

bench_profile() {
  local prof=$1
  log ">>> bench profile ${prof}"
  /usr/local/bin/spark inference down 2>/dev/null || true
  /usr/local/bin/spark recipe testing "$prof" >>"$LOG" 2>&1
  if ! /usr/local/bin/spark inference up "$prof" >>"$LOG" 2>&1; then
    log "FAIL inference up ${prof}"
    return 1
  fi
  local i ready=""
  for i in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:8767/api/inference/status" | grep -q '"ready":true'; then
      ready=1
      break
    fi
    sleep 15
  done
  if [[ -z "$ready" ]]; then
    log "FAIL engine not ready for ${prof}"
    /usr/local/bin/spark inference down >>"$LOG" 2>&1 || true
    return 1
  fi
  if BENCH_STANDARD=v2 /usr/local/bin/spark inference bench >>"$LOG" 2>&1; then
    log "OK bench ${prof}"
  else
    log "FAIL bench ${prof}"
    /usr/local/bin/spark inference down >>"$LOG" 2>&1 || true
    return 1
  fi
  /usr/local/bin/spark inference down >>"$LOG" 2>&1 || true
  wait_gpu_idle
}

print_summary() {
  log "=== Ornith quant A/B summary ==="
  for prof in "$BASELINE_PROF" "$FP8_PROF" "$NVFP4_PROF"; do
    /usr/local/bin/spark bench latest "$prof" 2>/dev/null | tee -a "$LOG" || log "(no bench yet for ${prof})"
    echo "---" | tee -a "$LOG"
  done
}

usage() {
  cat <<EOF
Usage: $(basename "$0") <command>

  download   Start HF downloads for FP8 + NVFP4 (if missing)
  prepare    Write eugr recipes/services + bench context
  wait       Block until fp8/ and nvfp4/ downloads are stable
  bench      Run bench-agent-v2 on baseline, FP8, NVFP4 (sequential)
  all        download -> wait -> prepare -> bench -> summary
  summary    Print latest bench results for all three profiles

Log: ${LOG}
EOF
}

cmd=${1:-all}
case "$cmd" in
  download) start_downloads ;;
  prepare) write_services_and_recipes; update_bench_context; /usr/local/bin/spark models inventory >>"$LOG" 2>&1 || true ;;
  wait)
    wait_stable_dir "${MODEL_ROOT}/fp8" "Ornith-1.0-35B-FP8"
    wait_stable_dir "${MODEL_ROOT}/nvfp4" "ModelOpt-NVFP4-Expert"
    ;;
  bench)
    wait_gpu_idle
    bench_profile "$FP8_PROF" || true
    bench_profile "$NVFP4_PROF" || true
    # Optional baseline re-bench (already golden @ 28.1 tok/s):
    # bench_profile "$BASELINE_PROF" || true
    print_summary
    ;;
  summary) print_summary ;;
  all)
    log "=== ornith quant A/B started pid=$$ ==="
    start_downloads
    write_services_and_recipes
    update_bench_context
    wait_stable_dir "${MODEL_ROOT}/fp8" "Ornith-1.0-35B-FP8"
    wait_stable_dir "${MODEL_ROOT}/nvfp4" "ModelOpt-NVFP4-Expert"
    /usr/local/bin/spark models inventory >>"$LOG" 2>&1 || true
    bench_profile "$FP8_PROF" || true
    bench_profile "$NVFP4_PROF" || true
    print_summary
    log "=== ornith quant A/B DONE ==="
    rm -f "$PID_FILE"
    ;;
  *) usage; exit 1 ;;
esac
