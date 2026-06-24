#!/usr/bin/env python3
"""Patch spark-inference.py for benchmark v2."""
from pathlib import Path

p = Path("/opt/spark/scripts/spark-inference.py")
t = p.read_text()

t = t.replace(
    'BENCH_METHODS = frozenset({"bench", "bench-agent"})',
    'BENCH_METHODS = frozenset({"bench", "bench-agent", "bench-agent-v2"})',
)

needle = "_CTX_SPEC.loader.exec_module(ctxmod)\n"
insert = needle + """
_BENCH_V2_SPEC = importlib.util.spec_from_file_location(
    "spark_inference_bench_v2", ROOT / "scripts" / "spark-inference-bench-v2.py"
)
benchv2 = importlib.util.module_from_spec(_BENCH_V2_SPEC)
assert _BENCH_V2_SPEC.loader is not None
_BENCH_V2_SPEC.loader.exec_module(benchv2)
"""
if "spark_inference_bench_v2" not in t:
    t = t.replace(needle, insert)

old_sig = """def record_benchmark(
    profile_id: str,
    recipe: dict[str, Any],
    tok_s: float,
    *,
    method: str,
    completion_tokens: int | None = None,
    prompt_tokens: int | None = None,
    elapsed_s: float | None = None,
    note: str | None = None,
    tok_s_min: float | None = None,
    tok_s_max: float | None = None,
    sessions: int | None = None,
    turns_per_session: int | None = None,
    run_tok_s: list[float] | None = None,
) -> dict[str, Any]:"""
new_sig = old_sig.replace(
    "run_tok_s: list[float] | None = None,\n) -> dict[str, Any]:",
    "run_tok_s: list[float] | None = None,\n    **extra: Any,\n) -> dict[str, Any]:",
)
if old_sig in t:
    t = t.replace(old_sig, new_sig)
else:
    raise SystemExit("record_benchmark signature not found")

needle2 = "    if note:\n        entry[\"note\"] = note\n    run = append_benchmark_history_run("
insert2 = (
    "    if note:\n        entry[\"note\"] = note\n"
    "    for key, val in extra.items():\n"
    "        if val is not None:\n"
    "            entry[key] = val\n"
    "    run = append_benchmark_history_run("
)
if "for key, val in extra.items()" not in t:
    t = t.replace(needle2, insert2)

old_keys = """    for key in (
        "completion_tokens",
        "prompt_tokens",
        "elapsed_s",
        "tok_s_min",
        "tok_s_max",
        "sessions",
        "turns_per_session",
        "run_tok_s",
    ):"""
new_keys = """    for key in (
        "completion_tokens",
        "prompt_tokens",
        "elapsed_s",
        "tok_s_min",
        "tok_s_max",
        "sessions",
        "turns_per_session",
        "run_tok_s",
        "bench_standard_version",
        "context_fill_target_tokens",
        "tool_roundtrip_ok",
    ):"""
if '"bench_standard_version"' not in t:
    t = t.replace(old_keys, new_keys)

old_bench = """def cmd_bench(write_result: bool = False) -> int:
    try:
        result = run_benchmark()"""
new_bench = """def cmd_bench(write_result: bool = False) -> int:
    standard = os.environ.get("BENCH_STANDARD", "v2").strip().lower()
    try:
        if standard in {"v2", "2", "2.0", "bench-agent-v2"}:
            active = detect_active_profile()
            if not active:
                raise RuntimeError("no active profile")
            result = benchv2.run_benchmark_v2(
                profile_id=active["profile"],
                recipe=active["recipe"],
                engine_ready=engine_ready,
                record_benchmark=record_benchmark,
            )
        else:
            result = run_benchmark()"""
if "benchv2.run_benchmark_v2" not in t:
    t = t.replace(old_bench, new_bench)

t = t.replace(
    "bench — multi-turn agent-style timing on the active profile (avg of 3 sessions).",
    "bench — agent benchmark on active profile (default BENCH_STANDARD=v2: ~50k ctx + tools).",
)

p.write_text(t)
print("patched ok")
