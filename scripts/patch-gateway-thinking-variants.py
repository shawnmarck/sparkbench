#!/usr/bin/env python3
"""Add -think / base model variants to spark-inference-gateway."""
from pathlib import Path

path = Path("/opt/spark/scripts/spark-inference-gateway.py")
text = path.read_text()

if "THINKING_VARIANT_SUFFIX" in text:
    print("already patched")
    raise SystemExit(0)

text = text.replace(
    'THINKING_DISABLED_ENGINES = {"ds4"}\n\n\nQWEN_ENGINE_MARKERS',
    'THINKING_DISABLED_ENGINES = {"ds4"}\nTHINKING_VARIANT_SUFFIX = "-think"\n\n\nQWEN_ENGINE_MARKERS',
    1,
)

helpers = '''

def _is_qwen_active(engine: str | None, served: str | None) -> bool:
    if not served:
        return False
    if (engine or "").lower() in QWEN_ENGINE_MARKERS:
        return True
    return "qwen" in served.lower()


def _thinking_variant_ids(served: str) -> tuple[str, str]:
    return served, f"{served}{THINKING_VARIANT_SUFFIX}"


def _resolve_thinking_variant(model: str, served: str | None, engine: str | None) -> tuple[str, bool | None]:
    """Map gateway model id -> upstream served id + optional enable_thinking override."""
    model = str(model or "").strip()
    if not model or not served or not _is_qwen_active(engine, served):
        return model, None
    fast_id, think_id = _thinking_variant_ids(served)
    if model == think_id:
        return served, True
    if model == fast_id:
        return served, False
    return model, None


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

'''

text = text.replace(
    "def _normalize_chat_payload(payload: dict[str, Any], engine: str | None) -> dict[str, Any]:",
    helpers + "\ndef _normalize_chat_payload(payload: dict[str, Any], engine: str | None) -> dict[str, Any]:",
    1,
)

old_get = """    def do_GET(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(404)
            return
        self._forward("GET", self.path)"""

new_get = """    def _serve_models(self) -> None:
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
        self._forward("GET", self.path)"""

text = text.replace(old_get, new_get, 1)

old_post = """                    if served and orig_model:
                        payload["model"] = served

                    payload = _normalize_chat_payload(payload, engine)"""

new_post = """                    payload = _apply_thinking_variant(payload, orig_model, served, engine)
                    if served and orig_model and _resolve_thinking_variant(orig_model, served, engine)[1] is None:
                        payload["model"] = served

                    payload = _normalize_chat_payload(payload, engine)"""

text = text.replace(old_post, new_post, 1)

doc_old = "- Passthrough most /v1/* ; special handling for models + chat."
doc_new = (
    "- Passthrough most /v1/* ; models list adds Qwen fast/thinking variants; chat applies them."
)
text = text.replace(doc_old, doc_new, 1)

path.write_text(text)
print("patched spark-inference-gateway.py")
