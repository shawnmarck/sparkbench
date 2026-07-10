#!/usr/bin/env python3
"""After overnight + PBM loop2: mark stubborn failures in the UI with notes.

Policy: a few troubleshooting passes are enough. Remaining broken inventory
paths → spark_status=failed + note. Recipe-only variants (inventory still
works) → recipe.notes / last_error, leave inventory alone.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path("/opt/spark")
VERIFY = ROOT / "data" / "model-verification.yaml"
GOLDEN = ROOT / "data" / "golden-recipes.yaml"
OVERNIGHT_STATE = ROOT / "run" / "full-coverage-state.json"
PBM_STATE = ROOT / "run" / "pbm-loop2-state.json"
PBM_FILE = ROOT / "data" / "perfbench-metrics.yaml"
REPORT = ROOT / "run" / "post-loops-triage-review.md"


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def save_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def verify_set(inv: str, status: str, note: str, engine: str | None = None) -> None:
    cmd = [
        str(ROOT / "venv/bin/python"),
        str(ROOT / "scripts" / "spark-model-verify"),
        "set",
        inv,
        status,
    ]
    if engine:
        cmd.append(engine)
    else:
        cmd.append("")
    cmd.append(note)
    # spark-model-verify: set PATH STATUS [engine] [note] — empty engine awkward.
    # Prefer: set PATH failed note via positional when engine omitted.
    cmd = [
        str(ROOT / "venv/bin/python"),
        str(ROOT / "scripts" / "spark-model-verify"),
        "set",
        inv,
        status,
    ]
    # API: set_status(rel, status, engine=None, note=None) via argv
    # argv[3]=status, argv[4]=engine OR note if not engine-like
    # Looking at script again...
    subprocess.run(
        [
            str(ROOT / "venv/bin/python"),
            str(ROOT / "scripts" / "spark-model-verify"),
            "set",
            inv,
            status,
            engine or "eugr",
            note,
        ],
        check=False,
    )


def annotate_recipe(profile_id: str, note: str) -> None:
    for base in (ROOT / "recipes", ROOT / "recipes" / "drafts"):
        path = base / f"{profile_id}.yaml"
        if not path.is_file():
            continue
        data = load_yaml(path)
        data["last_error"] = note
        data["last_error_at"] = datetime.now(timezone.utc).isoformat()
        existing = (data.get("notes") or "").strip()
        tag = f"[triage] {note}"
        if tag not in existing:
            data["notes"] = f"{existing}\n{tag}".strip() if existing else tag
        # Keep lifecycle testing (no failed lifecycle); UI reads verify for models
        if (data.get("lifecycle") or "").lower() == "works":
            # demote recipe-only failures off works
            data["lifecycle"] = "testing"
        save_yaml(path, data)
        print(f"annotated recipe {profile_id}")
        return
    print(f"no recipe file for {profile_id}")


# Known / overnight failures → inventory or recipe notes
INVENTORY_FAILURES: list[tuple[str, str, str | None]] = [
    (
        "0xsero/deepseek-v4-flash-spark",
        "REAP GGUF load blocked (needs dsv4 llama variant). Not supported on current llama.cpp build.",
        "llamacpp",
    ),
    (
        "nvidia/nvidia-nemotron-labs-3-puzzle-75b-a9b",
        "GB10 unified memory OOM (NV_ERR_NO_MEMORY) loading 75B NVFP4+MTP — cannot run on single Spark.",
        "eugr",
    ),
    (
        "z-lab/qwen3.6-35b-a3b",
        "DFlash + MoE: KV page-size AssertionError on vLLM 0.23.1rc1 even with FP8 target. Sidecar present; engine blocked.",
        "eugr",
    ),
    (
        "yuxinlu1/gemma-4-12b-agentic-fable5-composer2.5-v2-3.5x-tau2",
        "On disk under hf/*.gguf but scaffold cannot find weights (expects top-level gguf or nvfp4/hf). Needs manual llamacpp recipe pointing at hf/gemma4-v2-Q4_K_M.gguf.",
        "llamacpp",
    ),
]

# Recipe-only (do not fail parent inventory)
RECIPE_FAILURES: list[tuple[str, str]] = [
    (
        "nvidia-qwen3-6-27b-dflash-n10-32k",
        "Engine crash on load (vLLM init failed within ~15s). Parent nvidia/qwen3.6-27b dense @11.1 tok/s still works — DFlash variant not usable yet.",
    ),
]


def overnight_failures(state: dict) -> list[tuple[str, str]]:
    out = []
    for key, val in (state.get("items") or {}).items():
        sval = str(val)
        if not sval.startswith("failed") and "failed" not in sval:
            continue
        out.append((key, sval))
    return out


def main() -> int:
    overnight = {}
    if OVERNIGHT_STATE.is_file():
        overnight = json.loads(OVERNIGHT_STATE.read_text())
    pbm_state = {}
    if PBM_STATE.is_file():
        pbm_state = json.loads(PBM_STATE.read_text())

    # Apply inventory failures
    for inv, note, eng in INVENTORY_FAILURES:
        verify_set(inv, "failed", note, engine=eng)
        print(f"verify failed {inv}")

    # qwen official 35b — if overnight failed and still no tok_s
    verify = load_yaml(VERIFY).get("models") or {}
    q35 = verify.get("qwen/qwen3.6-35b-a3b") or {}
    if q35.get("spark_status") != "works" or q35.get("tok_s") is None:
        # Prefer overnight detail
        detail = (overnight.get("items") or {}).get("qwen/qwen3.6-35b-a3b") or ""
        note = (
            "Official Qwen3.6-35B-A3B DFlash/dense path failed overnight bench "
            f"({detail or 'no successful bench-v2'}). nvidia/qwen3.6-35b-a3b @58.9 remains the working 35B golden."
        )
        verify_set("qwen/qwen3.6-35b-a3b", "failed", note, engine="eugr")
        annotate_recipe("qwen-qwen3-6-35b-a3b-dflash-eugr", note)
        print("verify failed qwen/qwen3.6-35b-a3b")

    for pid, note in RECIPE_FAILURES:
        annotate_recipe(pid, note)

    # Map overnight failed keys that look like inventory paths
    for key, sval in overnight_failures(overnight):
        if "/" in key and key.count("/") == 1:
            # inventory path
            if key in {i[0] for i in INVENTORY_FAILURES}:
                continue
            existing = (verify.get(key) or {}).get("spark_status")
            if existing == "works" and (verify.get(key) or {}).get("tok_s") is not None:
                continue
            verify_set(
                key,
                "failed",
                f"Overnight full-coverage failed after retries: {sval}",
                engine="eugr",
            )
            print(f"overnight inventory fail {key}: {sval}")
        elif key.endswith(("-eugr", "-llama", "-dflash", "-32k", "-128k", "-n10")) or key.startswith(
            ("qwen-", "nvidia-", "aeon-", "poolside-", "s-batman-")
        ):
            annotate_recipe(key, f"Overnight failed: {sval}")

    # PBM failures — annotate recipes, don't demote works inventory solely for PBM miss
    for key, sval in (pbm_state.get("items") or {}).items():
        if str(sval).startswith("failed"):
            annotate_recipe(key, f"PBM loop2 failed: {sval}")

    # Any testing recipe still missing bench-v2 tok_s after overnight → annotate
    benches = (load_yaml(ROOT / "data" / "inference-benchmarks.yaml").get("profiles") or {})
    for path in sorted((ROOT / "recipes").glob("*.yaml")):
        data = load_yaml(path)
        life = (data.get("lifecycle") or "").lower()
        if life not in ("testing", "works", "production"):
            continue
        pid = data.get("id") or path.stem
        inv = data.get("inventory_path") or ""
        if inv in {i[0] for i in INVENTORY_FAILURES}:
            continue
        if pid in benches and benches[pid].get("tok_s") is not None:
            continue
        if life == "testing":
            note = (
                f"Still testing with no bench-v2 tok/s after overnight/PBM. "
                f"Inventory={inv or '—'}. Marked for human review."
            )
            annotate_recipe(pid, note)
            # If this is the only/golden recipe for an inventory without tok_s, fail inventory
            v = verify.get(inv) or {}
            if inv and (v.get("tok_s") is None) and v.get("spark_status") != "works":
                verify_set(
                    inv,
                    "failed",
                    note,
                    engine=data.get("engine") or "eugr",
                )

    # Rebuild inventory for portal
    subprocess.run(
        [str(ROOT / "venv/bin/python"), str(ROOT / "scripts" / "spark-inventory-build.py")],
        check=False,
    )

    # Report
    verify = load_yaml(VERIFY).get("models") or {}
    lines = [
        f"# Post-loops triage — {datetime.now(timezone.utc).isoformat()}",
        "",
        "Failures after overnight + PBM (stubborn after retries) are `failed` in the UI with notes.",
        "",
        "| inventory | status | tok/s | note |",
        "|---|---|---:|---|",
    ]
    for k, m in sorted(verify.items()):
        if m.get("spark_status") != "failed":
            continue
        lines.append(
            f"| `{k}` | failed | {m.get('tok_s') if m.get('tok_s') is not None else '—'} | "
            f"{(m.get('note') or '')[:160]} |"
        )
    lines += ["", "## Recipe last_error annotations"]
    for path in sorted((ROOT / "recipes").glob("*.yaml")):
        data = load_yaml(path)
        if data.get("last_error"):
            lines.append(f"- `{data.get('id') or path.stem}`: {data['last_error'][:200]}")
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
