#!/usr/bin/env python3
"""Spark Inference Gateway: unified stable /v1 endpoint on :9000.

Forwards to the active engine (eugr/ds4 on :8000 or llama on :8081).
- Reads active profile from core (state + runtime checks).
- Optional model aliases + auto-switch on chat/completions (triggers background switch).
- Returns 503 + Retry-After while no active or switching.
- Basic normalization (e.g. ds4 thinking disabled).
- Streaming-aware forwarding for SSE / completions.
- Passthrough most /v1/* ; models list adds Qwen fast/thinking variants + stable "sparky" alias; chat applies them.
- "sparky" (and "sparky-think") in /v1/models and chat always uses the active served model (no auto-switch).
- Records each chat/completions + completions (stream and non-stream) as a session row appended to
  run/inference-activity.jsonl (non-blocking background thread; Authorization header stripped).
  Consumed by spark-client-activity.py (:8769) → Portal System-tab widget.

Usage:
  python scripts/spark-inference-gateway.py --serve --port 9000
  # or via wrapper

Clients: http://sparky:9000/v1   (base_url for Hermes, Open WebUI, etc.)
Stable forever; backend port moves on `spark inference up <profile>`.

See docs/reference/inference-stack.md .
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path("/opt/spark")
SPEC = importlib.util.spec_from_file_location(
    "inference_core", ROOT / "scripts" / "spark-inference.py"
)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("failed to load spark-inference core")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

DEFAULT_PORT = 9000
UPSTREAM_HOST = "127.0.0.1"

# Model alias -> profile_id map. Extend as needed.
ALIASES: dict[str, str] = {
    "hermes-local": "nousresearch-hermes-4-14b-eugr",
    "hermes-14b": "nousresearch-hermes-4-14b-eugr",
    "qwen-local": "opencode-qwen27-dflash-262k",
    "qwen3-6-27b": "opencode-qwen27-dflash-262k",
    "qwen3.6-27b-dflash": "opencode-qwen27-dflash-262k",
    "step-3-7-flash": "stepfun-ai-step-3-7-flash-llama",
}

# Stable model id that always maps to the *currently active* served model (no switch).
# Clients (e.g. Grok ~/.grok/config.toml) can use a fixed [model.sparky] entry pointing at this.
SPARKY_MODEL_ID = "sparky"

THINKING_DISABLED_ENGINES = {"ds4"}
THINKING_VARIANT_SUFFIX = "-think"


QWEN_ENGINE_MARKERS = ("eugr", "vllm", "ds4")

# --- Activity logger ---
_ACTIVITY_LOCK = threading.Lock()
_JSONL_PATH: Path | None = None
_JSONL_FD = None
_JSONL_MAX_BYTES = 50 * 1024 * 1024  # 50 MB cap
_JSONL_MAX_AGE_S = 7 * 86400  # 7 days


def _classify_app(user_agent: str, spark_client: str | None) -> str:
    if spark_client:
        sc = spark_client.lower()
        if "hermes" in sc:
            return "hermes"
        if "open-webui" in sc or "openwebui" in sc:
            return "open-webui"
        if "opencode" in sc:
            return "opencode"
        return sc
    ua = (user_agent or "").lower()
    if "hermes" in ua:
        return "hermes"
    if "open-webui" in ua or "openwebui" in ua:
        return "open-webui"
    if "opencode" in ua:
        return "opencode"
    if any(k in ua for k in ("curl", "python-requests", "httpie", "axios", "httpx", "fetch", "wget")):
        return "script"
    return "unknown"


def _init_activity_logger(jsonl_path: str | None = None) -> None:
    global _JSONL_PATH, _JSONL_FD, _JSONL_MAX_BYTES, _JSONL_MAX_AGE_S
    _JSONL_PATH = Path(jsonl_path or (ROOT / "run" / "inference-activity.jsonl"))
    dirname = _JSONL_PATH.parent
    if not dirname.exists():
        dirname.mkdir(parents=True, exist_ok=True)
    _ensure_jsonl_fd()


def _ensure_jsonl_fd() -> None:
    global _JSONL_FD
    if _JSONL_FD is not None:
        try:
            fst = os.fstat(_JSONL_FD)
        except OSError:
            _JSONL_FD = None
        else:
            if fst.st_size > _JSONL_MAX_BYTES or (
                _JSONL_MAX_AGE_S > 0 and time.time() - fst.st_mtime > _JSONL_MAX_AGE_S
            ):
                try:
                    os.close(_JSONL_FD)
                except OSError:
                    pass
                _JSONL_FD = None
            else:
                return
    try:
        _rotate_jsonl_if_needed()
        _JSONL_FD = os.open(str(_JSONL_PATH), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    except OSError:
        pass


def _rotate_jsonl_if_needed() -> None:
    try:
        st = os.stat(str(_JSONL_PATH))
    except OSError:
        return
    if st.st_size > _JSONL_MAX_BYTES:
        try:
            truncated = _JSONL_PATH.with_suffix(".jsonl.truncated")
            with open(str(_JSONL_PATH), "r") as f:
                lines = f.readlines()
            if len(lines) > 10_000:
                lines = lines[len(lines) - 10_000:]
            with open(str(truncated), "w") as f:
                f.writelines(lines)
            with open(str(_JSONL_PATH), "w") as f:
                f.writelines(lines[-5000:])
        except OSError:
            pass
    if _JSONL_MAX_AGE_S > 0:
        age = time.time() - st.st_mtime
        if age > _JSONL_MAX_AGE_S:
            try:
                os.remove(str(_JSONL_PATH))
            except OSError:
                pass


def _append_activity(session: dict[str, Any]) -> None:
    if _JSONL_PATH is None:
        return
    thread = threading.Thread(target=_append_activity_sync, args=(session,), daemon=True)
    thread.start()


def _append_activity_sync(session: dict[str, Any]) -> None:
    global _JSONL_FD
    with _ACTIVITY_LOCK:
        _ensure_jsonl_fd()
        if _JSONL_FD is None:
            return
        try:
            line = json.dumps(session, separators=(",", ":")) + "\n"
            os.write(_JSONL_FD, line.encode("utf-8", errors="replace"))
            os.fsync(_JSONL_FD)
        except OSError:
            pass


# --- End activity logger ---


def _message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and part.get("text"):
                    parts.append(str(part["text"]).strip())
                elif part.get("text"):
                    parts.append(str(part["text"]).strip())
        return "\n".join(p for p in parts if p)
    return str(content).strip()


def _needs_qwen_message_normalization(engine: str | None, model: str | None) -> bool:
    engine_s = (engine or "").lower()
    model_s = (model or "").lower()
    if engine_s in QWEN_ENGINE_MARKERS:
        return True
    return "qwen" in model_s


def _normalize_qwen_messages(messages: list[Any]) -> list[Any]:
    """Qwen chat templates require a single leading system message."""
    if not isinstance(messages, list) or not messages:
        return messages

    leading_system: list[str] = []
    normalized: list[Any] = []

    for msg in messages:
        if not isinstance(msg, dict):
            normalized.append(msg)
            continue
        role = str(msg.get("role") or "")
        if role in ("system", "developer"):
            content = _message_text(msg.get("content"))
            if not content:
                continue
            if normalized:
                # Mid-conversation system (plugins, task injectors) -> user wrapper.
                normalized.append(
                    {
                        "role": "user",
                        "content": f"[System instruction]\n{content}",
                    }
                )
            else:
                leading_system.append(content)
            continue
        normalized.append(msg)

    if leading_system:
        normalized.insert(
            0,
            {"role": "system", "content": "\n\n".join(leading_system)},
        )
    return normalized




def _is_qwen_active(engine: str | None, served: str | None) -> bool:
    if not served:
        return False
    if (engine or "").lower() in QWEN_ENGINE_MARKERS:
        return True
    return "qwen" in served.lower()


def _thinking_variant_ids(served: str) -> tuple[str, str]:
    return served, f"{served}{THINKING_VARIANT_SUFFIX}"


def _resolve_thinking_variant(model: str, served: str | None, engine: str | None) -> tuple[str, bool | None]:
    """Map gateway model id -> upstream served id + optional enable_thinking override.

    Supports the stable "sparky" / "sparky-think" / "sparky-fast" ids in addition
    to concrete served names and their -think/-fast variants.
    """
    m = str(model or "").strip()
    if not m or not served or not _is_qwen_active(engine, served):
        return m, None
    fast_id, think_id = _thinking_variant_ids(served)
    ml = m.lower()
    if ml in ("sparky", "sparky-fast") or m == served or m == fast_id:
        return served, False
    if ml == "sparky-think" or m == think_id:
        return served, True
    if ml == think_id.lower():
        return served, True
    if ml == fast_id.lower():
        return served, False
    if m == think_id:
        return served, True
    if m == fast_id:
        return served, False
    return m, None


def _apply_thinking_variant(payload: dict[str, Any], orig_model: str, served: str | None, engine: str | None) -> dict[str, Any]:
    upstream_model, think = _resolve_thinking_variant(orig_model, served, engine)
    if think is None:
        return payload
    payload = dict(payload)
    payload["model"] = upstream_model
    kwargs = dict(payload.get("chat_template_kwargs") or {})
    kwargs["enable_thinking"] = think
    payload["chat_template_kwargs"] = kwargs
    return payload


def _expand_models_payload(payload: dict[str, Any], served: str | None, engine: str | None) -> dict[str, Any]:
    if not served or not _is_qwen_active(engine, served):
        return payload
    data = payload.get("data")
    if not isinstance(data, list):
        return payload
    fast_id, think_id = _thinking_variant_ids(served)
    out: list[Any] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            out.append(item)
            continue
        mid = str(item.get("id") or "")
        if mid == served:
            fast = dict(item)
            fast["id"] = fast_id
            fast_name = fast.get("name") or fast_id
            if isinstance(fast_name, str) and "think" not in fast_name.lower():
                fast["name"] = f"{fast_name} (fast)"
            out.append(fast)
            seen.add(fast_id)
            think = dict(item)
            think["id"] = think_id
            think_name = think.get("name") or think_id
            if isinstance(think_name, str):
                think["name"] = (
                    think_name
                    if "think" in think_name.lower()
                    else f"{think_name} (thinking)"
                )
            out.append(think)
            seen.add(think_id)
            continue
        if mid in seen:
            continue
        out.append(item)
        if mid:
            seen.add(mid)
    payload = dict(payload)
    payload["data"] = out
    return payload


def _inject_sparky_alias(
    payload: dict[str, Any], served: str | None, profile: str | None
) -> dict[str, Any]:
    """Ensure a stable 'sparky' entry is present in /v1/models pointing at the active model.

    This allows Grok (and other static-config clients) to configure a single
    [model.sparky] entry using model="sparky" that always resolves to whatever
    profile is currently loaded on the gateway.
    """
    if not served:
        return payload
    data = payload.get("data")
    if not isinstance(data, list):
        data = []
    # Already present?
    for item in data:
        if isinstance(item, dict) and str(item.get("id") or "") == SPARKY_MODEL_ID:
            return payload

    # Clone metadata from any entry (prefer one whose id matches served or a fast variant)
    base: dict[str, Any] | None = None
    fast_id, think_id = _thinking_variant_ids(served) if served else (None, None)
    for item in data:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "")
        if mid == served or mid == fast_id or mid == think_id or served in mid:
            base = item
            break
    if base is None:
        for item in data:
            if isinstance(item, dict):
                base = item
                break

    entry: dict[str, Any] = dict(base) if base else {
        "id": SPARKY_MODEL_ID,
        "object": "model",
        "created": 0,
        "owned_by": "spark",
    }
    entry = dict(entry)
    entry["id"] = SPARKY_MODEL_ID
    entry["name"] = f"sparky ({served})"
    if profile:
        entry["spark_profile"] = profile
    # Put the stable alias first so it is prominent for clients that list models
    new_data: list[Any] = [entry] + [d for d in data]
    payload = dict(payload)
    payload["data"] = new_data
    return payload


def _normalize_chat_payload(payload: dict[str, Any], engine: str | None) -> dict[str, Any]:
    if not _needs_qwen_message_normalization(engine, str(payload.get("model") or "")):
        return payload
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return payload
    payload = dict(payload)
    payload["messages"] = _normalize_qwen_messages(messages)
    return payload



class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _get_active(self) -> tuple[int | None, str | None, str | None, dict[str, Any] | None]:
        try:
            active = core.detect_active_profile()
            if not active:
                return None, None, None, None
            recipe = active.get("recipe", {}) or {}
            port = int(recipe.get("port") or (8000 if recipe.get("engine") != "llamacpp" else 8081))
            served = recipe.get("served_name")
            prof = active.get("profile")
            return port, served, prof, active
        except Exception as exc:
            sys.stderr.write(f"gateway active lookup error: {exc}\n")
            return None, None, None, None

    def _is_switching(self) -> bool:
        try:
            job = core.active_switch_job()
            return bool(job.get("running"))
        except Exception:
            return False

    def _resolve_alias(self, model: str) -> str | None:
        if not model:
            return None
        model = str(model).strip()
        if model in ALIASES:
            return ALIASES[model]
        if core.validate_profile_id(model):
            return model
        return None

    def _inject_ds4_defaults(self, body: bytes, engine: str | None) -> bytes:
        if not body or engine not in THINKING_DISABLED_ENGINES:
            return body
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return body
            payload["thinking"] = {"type": "disabled"}
            payload["think"] = False
            payload.pop("reasoning_effort", None)
            return json.dumps(payload).encode()
        except (json.JSONDecodeError, TypeError):
            return body

    def _forward_with_activity(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        t0 = time.time()
        port, served, prof, active = self._get_active()
        recipe = (active or {}).get("recipe", {}) or {}
        engine = recipe.get("engine")
        model = ""
        is_stream = False
        try:
            payload = json.loads(body) if body else {}
            if isinstance(payload, dict):
                model = str(payload.get("model", "")).strip()
                is_stream = bool(payload.get("stream", False))
        except (json.JSONDecodeError, TypeError):
            pass

        client_ip = self.client_address[0] if hasattr(self, "client_address") else "unknown"
        ua = self.headers.get("User-Agent", "")
        spark_client = self.headers.get("X-Spark-Client", "")
        app = _classify_app(ua, spark_client)
        session = {
            "id": uuid.uuid4().hex[:16],
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
            "client_ip": client_ip,
            "app": app,
            "user_agent": ua,
            "model": model,
            "profile": prof or "",
            "engine": engine or "",
            "stream": is_stream,
            "status": "",
        }

        if not port:
            duration_ms = int((time.time() - t0) * 1000)
            session["duration_ms"] = duration_ms
            session["prompt_tokens"] = 0
            session["completion_tokens"] = 0
            session["tok_s"] = 0
            session["status"] = "503"
            _append_activity(session)
            self._forward(method, path, body=body, extra_headers=extra_headers)
            return

        if self._is_switching():
            duration_ms = int((time.time() - t0) * 1000)
            session["duration_ms"] = duration_ms
            session["prompt_tokens"] = 0
            session["completion_tokens"] = 0
            session["tok_s"] = 0
            session["status"] = "503"
            _append_activity(session)
            self._forward(method, path, body=body, extra_headers=extra_headers)
            return

        if not self._upstream_ready(port):
            duration_ms = int((time.time() - t0) * 1000)
            session["duration_ms"] = duration_ms
            session["prompt_tokens"] = 0
            session["completion_tokens"] = 0
            session["tok_s"] = 0
            session["status"] = "503"
            _append_activity(session)
            self._forward(method, path, body=body, extra_headers=extra_headers)
            return

        upstream = f"http://{UPSTREAM_HOST}:{port}{path}"
        headers: dict[str, str] = {}
        for k, v in self.headers.items():
            kl = k.lower()
            if kl not in ("host", "connection", "content-length"):
                headers[k] = v
        if extra_headers:
            headers.update(extra_headers)
        if body is not None:
            headers.setdefault("Content-Type", "application/json")

        req = Request(upstream, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=600) as resp:
                ctype = resp.headers.get("Content-Type", "application/json")
                status = resp.status

                if is_stream and "text/event-stream" in (ctype or ""):
                    self._forward_stream_activity(resp, ctype, status, session, t0, served, prof)
                else:
                    resp_body = resp.read()
                    duration_ms = int((time.time() - t0) * 1000)
                    session["duration_ms"] = duration_ms
                    session["status"] = str(status)
                    try:
                        j = json.loads(resp_body) if resp_body else {}
                        usage = j.get("usage") or {}
                        pt = usage.get("prompt_tokens") or 0
                        ct = usage.get("completion_tokens") or 0
                    except (json.JSONDecodeError, TypeError):
                        pt, ct = 0, 0
                    session["prompt_tokens"] = pt
                    session["completion_tokens"] = ct
                    d_s = duration_ms / 1000 if duration_ms > 0 else 0.001
                    session["tok_s"] = round((ct / d_s) if ct else 0, 1)
                    _append_activity(session)
                    self.send_response(status)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Spark-Active-Profile", prof or "")
                    self.send_header("X-Spark-Upstream-Port", str(port))
                    if served:
                        self.send_header("X-Spark-Served-Model", served)
                    self._cors()
                    self.end_headers()
                    if resp_body:
                        self.wfile.write(resp_body)
                        try:
                            self.wfile.flush()
                        except Exception:
                            pass
        except HTTPError as exc:
            duration_ms = int((time.time() - t0) * 1000)
            session["duration_ms"] = duration_ms
            session["prompt_tokens"] = 0
            session["completion_tokens"] = 0
            session["tok_s"] = 0
            session["status"] = str(exc.code)
            _append_activity(session)
            ctype = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
            self.send_response(exc.code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            err_body = exc.read()
            if err_body:
                self.wfile.write(err_body)
        except URLError as exc:
            duration_ms = int((time.time() - t0) * 1000)
            session["duration_ms"] = duration_ms
            session["prompt_tokens"] = 0
            session["completion_tokens"] = 0
            session["tok_s"] = 0
            session["status"] = "502"
            _append_activity(session)
            payload = json.dumps(
                {"error": {"message": f"upstream error: {exc.reason}", "type": "gateway_upstream"}}
            ).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            duration_ms = int((time.time() - t0) * 1000)
            session["duration_ms"] = duration_ms
            session["prompt_tokens"] = 0
            session["completion_tokens"] = 0
            session["tok_s"] = 0
            session["status"] = "500"
            _append_activity(session)
            payload = json.dumps(
                {"error": {"message": f"gateway error: {exc}", "type": "gateway"}}
            ).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

    def _forward_stream_activity(
        self,
        resp: Any,
        ctype: str,
        status: int,
        session: dict[str, Any],
        t0: float,
        served: str | None,
        prof: str | None,
    ) -> None:
        chunk_size = 8192
        collected = bytearray()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Spark-Active-Profile", prof or "")
        self.send_header("X-Spark-Upstream-Port", str(resp.headers.get("X-Spark-Upstream-Port", "")))
        if served:
            self.send_header("X-Spark-Served-Model", served)
        self._cors()
        self.end_headers()
        client_gone = False
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            collected.extend(chunk)
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except Exception:
                client_gone = True
                break
        duration_ms = int((time.time() - t0) * 1000)
        session["duration_ms"] = duration_ms
        session["status"] = "disconnect" if client_gone else str(status)
        pt, ct = self._extract_stream_usage(collected)
        session["prompt_tokens"] = pt
        session["completion_tokens"] = ct
        d_s = duration_ms / 1000 if duration_ms > 0 else 0.001
        session["tok_s"] = round((ct / d_s) if ct else 0, 1)
        _append_activity(session)

    def _extract_stream_usage(self, collected: bytearray) -> tuple[int, int]:
        try:
            text = collected.decode("utf-8", errors="replace")
            pt, ct = 0, 0
            for line in text.split("\n"):
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    usage = obj.get("usage")
                    if usage:
                        pt = usage.get("prompt_tokens") or 0
                        ct = usage.get("completion_tokens") or 0
                except (json.JSONDecodeError, TypeError):
                    continue
            if not pt and not ct:
                for line in reversed(text.split("\n")):
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        usage = obj.get("usage")
                        if usage:
                            pt = usage.get("prompt_tokens") or 0
                            ct = usage.get("completion_tokens") or 0
                            break
                    except (json.JSONDecodeError, TypeError):
                        continue
            return pt, ct
        except Exception:
            return 0, 0

    def _forward(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        port, served, prof, active = self._get_active()
        if not port:
            self._send_503("no active inference profile — run: spark inference up <profile>")
            return

        if self._is_switching():
            self._send_503(
                "profile switch in progress",
                retry_after=30,
                extra={"switching": True, "profile": prof},
            )
            return

        if not self._upstream_ready(port):
            self._send_503(
                "active engine not ready yet (loading or cold start)",
                retry_after=15,
                extra={"port": port, "profile": prof},
            )
            return

        recipe = (active or {}).get("recipe", {}) or {}
        engine = recipe.get("engine")

        upstream = f"http://{UPSTREAM_HOST}:{port}{path}"
        headers: dict[str, str] = {}
        for k, v in self.headers.items():
            kl = k.lower()
            if kl not in ("host", "connection", "content-length"):
                headers[k] = v
        if extra_headers:
            headers.update(extra_headers)
        if body is not None:
            headers.setdefault("Content-Type", "application/json")

        req = Request(upstream, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=600) as resp:
                ctype = resp.headers.get("Content-Type", "application/json")
                status = resp.status
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Spark-Active-Profile", prof or "")
                self.send_header("X-Spark-Upstream-Port", str(port))
                if served:
                    self.send_header("X-Spark-Served-Model", served)
                self._cors()
                self.end_headers()

                chunk_size = 8192
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    try:
                        self.wfile.flush()
                    except Exception:
                        pass
        except HTTPError as exc:
            ctype = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
            self.send_response(exc.code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            body = exc.read()
            if body:
                self.wfile.write(body)
        except URLError as exc:
            payload = json.dumps(
                {"error": {"message": f"upstream error: {exc.reason}", "type": "gateway_upstream"}}
            ).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            payload = json.dumps(
                {"error": {"message": f"gateway error: {exc}", "type": "gateway"}}
            ).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

    def _upstream_ready(self, port: int) -> bool:
        try:
            url = f"http://{UPSTREAM_HOST}:{port}/v1/models"
            with urlopen(url, timeout=3.0) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def _send_503(self, message: str, retry_after: int = 30, extra: dict[str, Any] | None = None) -> None:
        payload = {
            "error": {
                "message": message,
                "type": "inference_unavailable",
            }
        }
        if extra:
            payload.update(extra)
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Retry-After", str(retry_after))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _serve_models(self) -> None:
        port, served, prof, active = self._get_active()
        if not port:
            self._send_503("no active inference profile — run: spark inference up <profile>")
            return
        if self._is_switching():
            self._send_503("profile switch in progress", retry_after=30, extra={"switching": True, "profile": prof})
            return
        if not self._upstream_ready(port):
            self._send_503(
                "active engine not ready yet (loading or cold start)",
                retry_after=15,
                extra={"port": port, "profile": prof},
            )
            return
        recipe = (active or {}).get("recipe", {}) or {}
        engine = recipe.get("engine")
        upstream = f"http://{UPSTREAM_HOST}:{port}{self.path}"
        try:
            with urlopen(upstream, timeout=10) as resp:
                payload = json.loads(resp.read().decode())
            if isinstance(payload, dict):
                payload = _expand_models_payload(payload, served, engine)
                payload = _inject_sparky_alias(payload, served, prof)
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Spark-Active-Profile", prof or "")
            self.send_header("X-Spark-Upstream-Port", str(port))
            if served:
                self.send_header("X-Spark-Served-Model", served)
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        except HTTPError as exc:
            ctype = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
            self.send_response(exc.code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            err_body = exc.read()
            if err_body:
                self.wfile.write(err_body)
        except (URLError, json.JSONDecodeError, OSError, ValueError) as exc:
            payload = json.dumps(
                {"error": {"message": f"gateway models error: {exc}", "type": "gateway"}}
            ).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

    def do_GET(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(404)
            return
        if self.path.startswith("/v1/models"):
            self._serve_models()
            return
        self._forward("GET", self.path)

    def do_POST(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(404)
            return

        body = self._read_body()
        is_completion = "chat/completions" in self.path or "completions" in self.path

        if is_completion:
            try:
                payload = json.loads(body) if body else {}
                if isinstance(payload, dict):
                    orig_model = str(payload.get("model", "")).strip()
                    profile = self._resolve_alias(orig_model)
                    port, served, prof, active = self._get_active()
                    engine = (active or {}).get("recipe", {}).get("engine") if active else None

                    if profile and prof and profile != prof:
                        try:
                            ok, msg, job = core.start_switch_job(profile)
                            retry = 60 if "heavy" in str((active or {}).get("recipe", {}).get("tier", "") or "").lower() else 20
                            self._send_503(
                                f"Switching to profile '{profile}' (model '{orig_model}'). Retry ~{retry}s.",
                                retry_after=retry,
                                extra={"switching": True, "target_profile": profile, "job": job},
                            )
                            return
                        except Exception as sw_exc:
                            sys.stderr.write(f"gateway auto-switch error: {sw_exc}\n")

                    payload = _apply_thinking_variant(payload, orig_model, served, engine)
                    if served and orig_model and _resolve_thinking_variant(orig_model, served, engine)[1] is None:
                        payload["model"] = served

                    payload = _normalize_chat_payload(payload, engine)
                    body = json.dumps(payload).encode()
                    body = self._inject_ds4_defaults(body, engine)

            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            self._forward_with_activity("POST", self.path, body=body)
        else:
            self._forward("POST", self.path, body=body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()


def main() -> int:
    parser = argparse.ArgumentParser(description="Spark unified inference gateway")
    parser.add_argument("--serve", action="store_true", help="Run server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--list-aliases", action="store_true")
    args = parser.parse_args()

    if args.list_aliases:
        print(json.dumps(ALIASES, indent=2))
        return 0

    if not args.serve:
        parser.print_help()
        print("\nRun: /opt/spark/scripts/spark-inference-gateway --serve --port 9000")
        return 1

    ThreadingHTTPServer.allow_reuse_address = True
    _init_activity_logger()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"spark-inference-gateway listening on http://{args.host}:{args.port}/v1")
    print(f"  Stable client endpoint: http://sparky:{args.port}/v1")
    print(f"  Aliases configured: {list(ALIASES.keys())}")
    print(f"  Stable model ids (always current): {SPARKY_MODEL_ID}, {SPARKY_MODEL_ID}-think, {SPARKY_MODEL_ID}-fast")
    print("  Forwarding to active engine per spark inference state.")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
