#!/usr/bin/env python3
"""TASK-004 backend evidence test — exercises the new spark-hf.py API logic.

Verifies, against the real module code:
  1. _explore_item_status() priority: downloading > download_queued > gated > on_disk > saved
  2. queue_list() enriches every explore item with a `status` field
  3. queue_add_explore() persists a snapshot (only whitelisted keys)
  4. queue_add_explore() dedupes by (repo, intent, inventory_path), preserving
     the stable id + added_at so UI selections survive re-saves.

The module hardcodes /opt/spark paths, so we monkeypatch the filesystem-touching
helpers to an in-memory store and a temp models root. The functions under test
are otherwise exercised verbatim.
"""
import importlib.util
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "spark-hf.py"

spec = importlib.util.spec_from_file_location("spark_hf", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# --- in-memory explore-queue store + stubs -------------------------------
_store = {"items": []}
m._ensure_explore_download_allowed = lambda repo: None  # no warnings in test
_eq = (lambda: dict(items=list(_store.get("items", []))))
m.load_explore_queue = _eq
_sq = (lambda data: _store.update(items=list(data.get("items", []))))
m.save_explore_queue = _sq
m.prune_download_queue = lambda persist=True: 0
m.active_hf_download = lambda: {}
m.can_start_download = lambda defer_bench=True: (True, "")
_dl_store = {"items": []}
m.load_download_queue = lambda: {"items": list(_dl_store["items"])}

# temp models root so on_disk check is deterministic
_tmp = tempfile.TemporaryDirectory()
m.MODELS_ROOT = Path(_tmp.name)

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    flag = "PASS" if cond else "FAIL"
    print(f"  [{flag}] {name}" + (f"  -- {detail}" if (detail and not cond) else ""))


def reset():
    _store["items"] = []
    _dl_store["items"] = []
    # wipe temp models root so on_disk checks don't leak across cases
    for child in m.MODELS_ROOT.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


print("== 1. _explore_item_status() priority chain ==")
reset()
repo = "org/model-a"
# downloading
_dl_store["items"] = [{"repo": repo, "state": m.STATE_DOWNLOADING, "plan": {}}]
check("downloading wins",
      m._explore_item_status({"repo": repo}, _dl_store["items"]) == "downloading")
# download_queued
_dl_store["items"] = [{"repo": repo, "state": m.STATE_QUEUED, "plan": {}}]
check("download_queued",
      m._explore_item_status({"repo": repo}, _dl_store["items"]) == "download_queued")
# gated
_dl_store["items"] = [{"repo": repo, "state": m.STATE_AWAITING, "plan": {}}]
check("gated", m._explore_item_status({"repo": repo}, _dl_store["items"]) == "gated")
# on_disk via inventory_path on temp models root
reset()
inv = "org/model-a/gguf-q4"
dest = m.MODELS_ROOT / inv
dest.mkdir(parents=True)
(dest / "model.gguf").write_bytes(b"x")
check("on_disk (resolved via inventory_path)",
      m._explore_item_status({"repo": repo, "inventory_path": inv}, []) == "on_disk")
# saved (nothing on disk, nothing in queue)
reset()
check("saved (default)",
      m._explore_item_status({"repo": "org/other", "inventory_path": "x/y"}, []) == "saved")
# inventory_path mismatch does NOT match a different dl item
reset()
_dl_store["items"] = [{"repo": repo, "state": m.STATE_QUEUED,
                       "plan": {"inventory_path": "other/path"}}]
check("ignores dl item with mismatched inventory_path",
      m._explore_item_status({"repo": repo, "inventory_path": inv}, _dl_store["items"]) == "saved",
      "expected saved because inventory_path differs")

print("\n== 2. queue_list() enriches explore items with status ==")
reset()
m.queue_add_explore(repo="org/m1", intent="gguf_best",
                    snapshot={"spark_fit": "recommended", "size_human": "4.0 GB"})
m.queue_add_explore(repo="org/m2", intent="gguf_best")
out = m.queue_list()
ex = out["explore"]
check("queue_list returns explore items", isinstance(ex, list) and len(ex) == 2)
check("every explore item has status", all("status" in i for i in ex))
check("explore item status is 'saved' when idle",
      all(i["status"] == "saved" for i in ex), str([(i["repo"], i["status"]) for i in ex]))

print("\n== 3. queue_add_explore() stores whitelisted snapshot keys only ==")
reset()
snap_in = {
    "format": "gguf", "engine": "llamacpp", "size_bytes": 4200000000,
    "size_human": "4.2 GB", "spark_fit": "recommended", "spark_fit_label": "Fits",
    "badges": ["gguf", "moe"], "dest": "/models/x", "downloads": 12345,
    # non-whitelisted keys that must be dropped:
    "evil_key": "should-not-persist", "id": "OVERWRITE_ATTEMPT",
}
item = m.queue_add_explore(repo="org/snap", intent="gguf_best", snapshot=snap_in)
stored = item["snapshot"]
allowed = {"format", "engine", "size_bytes", "size_human", "spark_fit",
           "spark_fit_label", "badges", "dest", "downloads"}
check("snapshot persisted", isinstance(stored, dict) and stored.get("spark_fit") == "recommended")
check("only whitelisted snapshot keys kept",
      set(stored.keys()) <= allowed, f"extra keys: {set(stored.keys()) - allowed}")
check("evil_key dropped", "evil_key" not in stored)
check("snapshot cannot overwrite item id", item["id"] != "OVERWRITE_ATTEMPT")

print("\n== 4. queue_add_explore() dedupe preserves stable id + added_at ==")
reset()
first = m.queue_add_explore(repo="org/dup", intent="gguf_best",
                            inventory_path="org/dup/q4",
                            snapshot={"spark_fit": "ok", "size_human": "5 GB"})
first_id = first["id"]
first_added = first["added_at"]
check("first add has id+added_at", bool(first_id) and bool(first_added))
# re-save with same (repo, intent, inventory_path) and a richer snapshot
second = m.queue_add_explore(repo="org/dup", intent="gguf_best",
                             inventory_path="org/dup/q4",
                             snapshot={"spark_fit": "recommended", "size_human": "5 GB",
                                       "badges": ["gguf"]})
check("dedupe keeps stable id", second["id"] == first_id,
      f"{second['id']} != {first_id}")
check("dedupe preserves added_at", second["added_at"] == first_added)
check("dedupe updates snapshot", second["snapshot"]["spark_fit"] == "recommended")
check("dedupe does not duplicate row", len(_store["items"]) == 1,
      f"rows={len(_store['items'])}")
# different intent or inventory_path -> new row
third = m.queue_add_explore(repo="org/dup", intent="nvfp4_best",
                            inventory_path="org/dup/q4")
check("different intent creates new row", third["id"] != first_id and len(_store["items"]) == 2)
fourth = m.queue_add_explore(repo="org/dup", intent="gguf_best",
                             inventory_path="org/dup/q5")
check("different inventory_path creates new row",
      fourth["id"] != first_id and len(_store["items"]) == 3)

print("\n== 5. new item gets a fresh uuid id on first save ==")
reset()
fresh = m.queue_add_explore(repo="org/fresh", intent="gguf_best")
try:
    uuid.UUID(fresh["id"])
    fresh_ok = True
except Exception:
    fresh_ok = False
check("first-save id is a valid uuid", fresh_ok)

print("\n" + "=" * 52)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("ALL BACKEND CHECKS PASSED")
