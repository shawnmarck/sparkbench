#!/usr/bin/env python3
"""Patch spark-eugr-check.py: write stack state without root when official path is read-only."""
from pathlib import Path

p = Path("/opt/spark/scripts/spark-eugr-check.py")
t = p.read_text()
if "PENDING_STATE_FILE" in t:
    print("already patched")
    raise SystemExit(0)

t = t.replace(
    'STATE_FILE = ROOT / "run" / "eugr-stack-state.json"\n',
    'STATE_FILE = ROOT / "run" / "eugr-stack-state.json"\n'
    'PENDING_STATE_FILE = ROOT / "run" / "eugr-stack-state.pending.json"\n',
)

old_load = """def load_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}"""

new_load = """def load_state() -> dict[str, Any]:
    for path in (STATE_FILE, PENDING_STATE_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except (OSError, json.JSONDecodeError):
            continue
    return {}"""

old_save = """def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\\n", encoding="utf-8")"""

new_save = """def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2) + "\\n"
    PENDING_STATE_FILE.write_text(payload, encoding="utf-8")
    try:
        STATE_FILE.write_text(payload, encoding="utf-8")
    except OSError:
        pass"""

if old_load not in t or old_save not in t:
    raise SystemExit("expected load_state/save_state blocks not found")
t = t.replace(old_load, new_load).replace(old_save, new_save)
p.write_text(t)
print("patched eugr state writable ok")
