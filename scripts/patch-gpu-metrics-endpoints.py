#!/usr/bin/env python3
"""One-shot patch for /opt/spark/scripts/spark-gpu-metrics on sparky."""
from pathlib import Path

path = Path("/opt/spark/scripts/spark-gpu-metrics")
text = path.read_text()

insert_after = "from pathlib import Path\n\n"
new_constants = """from pathlib import Path

SPARK_HOST = os.environ.get("SPARK_HOST", "sparky")
GATEWAY_PORT = int(os.environ.get("SPARK_GATEWAY_PORT", "9000"))
INFERENCE_CONTAINERS = frozenset({"vllm_node", "spark-vllm-qwen36", "vllm-node"})

"""

if "SPARK_HOST" not in text:
    text = text.replace(insert_after, new_constants, 1)

block = '''

def parse_docker_ports(ports_str: str) -> list[dict]:
    """Parse docker ps Ports column into host endpoints."""
    endpoints: list[dict] = []
    if not ports_str:
        return endpoints
    seen: set[int] = set()
    for part in ports_str.split(","):
        part = part.strip()
        if "->" not in part:
            continue
        host_part, _container_part = part.split("->", 1)
        host_part = host_part.replace("[::]:", "").replace("0.0.0.0:", "")
        host_port = host_part.split(":")[-1].split("/")[0]
        if not host_port.isdigit():
            continue
        port = int(host_port)
        if port in seen:
            continue
        seen.add(port)
        endpoints.append(
            {
                "port": port,
                "url": f"http://{SPARK_HOST}:{port}",
                "local_url": f"http://127.0.0.1:{port}",
            }
        )
    return endpoints


def read_docker_network_modes(names: list[str]) -> dict[str, str]:
    if not names:
        return {}
    try:
        out = subprocess.check_output(
            [
                "docker",
                "inspect",
                "-f",
                "{{.Name}}\\t{{.HostConfig.NetworkMode}}",
                *names,
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    modes: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        name, mode = line.split("\\t", 1)
        modes[name.lstrip("/")] = mode
    return modes


def _engine_endpoint(engine: dict, *, up: bool | None = None) -> dict:
    port = int(engine["port"])
    return {
        "label": engine.get("label") or engine.get("id") or "Engine",
        "port": port,
        "path": "/v1",
        "url": f"http://{SPARK_HOST}:{port}/v1",
        "local_url": f"http://127.0.0.1:{port}/v1",
        "up": engine.get("up") if up is None else up,
        "model": engine.get("model"),
        "kind": "engine",
    }


def _gateway_endpoint(gateway: dict) -> dict:
    port = int(gateway.get("port", GATEWAY_PORT))
    return {
        "label": "Gateway",
        "port": port,
        "path": "/v1",
        "url": gateway.get("url") or f"http://{SPARK_HOST}:{port}/v1",
        "local_url": gateway.get("local_url") or f"http://127.0.0.1:{port}/v1",
        "up": gateway.get("up", False),
        "model": gateway.get("model"),
        "kind": "gateway",
    }


def enrich_containers(containers: list[dict], inference: dict | None) -> list[dict]:
    """Attach reachable API URLs; host-network inference containers have no docker Ports."""
    inference = inference or {}
    network_modes = read_docker_network_modes([c["name"] for c in containers])
    engines = inference.get("engines") or []
    vllm_engine = next((e for e in engines if e.get("id") == "vllm"), None)
    llama_engine = next((e for e in engines if e.get("id") == "llamacpp"), None)
    gateway = inference.get("gateway") or {}
    active_engine = next((e for e in engines if e.get("up")), None)

    for c in containers:
        name = c["name"]
        mode = network_modes.get(name) or None
        c["network"] = mode
        endpoints: list[dict] = []

        if name in INFERENCE_CONTAINERS or mode == "host":
            if name in INFERENCE_CONTAINERS:
                c["role"] = "inference"
            if active_engine:
                endpoints.append(_engine_endpoint(active_engine))
            else:
                for eng in (vllm_engine, llama_engine):
                    if eng:
                        endpoints.append(_engine_endpoint(eng))
            if gateway:
                endpoints.append(_gateway_endpoint(gateway))
        elif name == "spark-open-webui":
            for ep in parse_docker_ports(c.get("ports", "")):
                endpoints.append(
                    {
                        "label": "Open WebUI",
                        "port": ep["port"],
                        "path": "",
                        "url": ep["url"],
                        "local_url": ep["local_url"],
                        "up": c.get("up", False),
                        "kind": "web",
                    }
                )
        elif name == "spark-bot":
            for ep in parse_docker_ports(c.get("ports", "")):
                endpoints.append(
                    {
                        "label": "Hermes",
                        "port": ep["port"],
                        "path": "",
                        "url": ep["url"],
                        "local_url": ep["local_url"],
                        "up": c.get("up", False),
                        "kind": "web",
                    }
                )
        else:
            for ep in parse_docker_ports(c.get("ports", "")):
                endpoints.append(
                    {
                        "label": f":{ep['port']}",
                        "port": ep["port"],
                        "path": "",
                        "url": ep["url"],
                        "local_url": ep["local_url"],
                        "up": c.get("up", False),
                        "kind": "port",
                    }
                )

        c["endpoints"] = endpoints
    return containers

'''

marker = 'HERMES_CONTAINER = "spark-bot"'
if "def enrich_containers" not in text:
    text = text.replace(marker, block + marker, 1)

old_read_inference = """def read_inference():
    llama_port = int(os.environ.get("SPARK_LLAMA_PORT", "8081"))
    probes = [
        {"id": "vllm", "label": "vLLM", "port": 8000},
        {"id": "llamacpp", "label": "llama.cpp", "port": llama_port},
    ]
    engines = []
    for probe in probes:
        status = probe_openai_models(f"http://127.0.0.1:{probe['port']}/v1/models")
        engines.append({**probe, **status})
    primary = next((e for e in engines if e["up"]), None)
    return {
        "up": primary is not None,
        "model": primary["model"] if primary else None,
        "engine": primary["id"] if primary else None,
        "engines": engines,
    }"""

new_read_inference = """def read_inference():
    llama_port = int(os.environ.get("SPARK_LLAMA_PORT", "8081"))
    probes = [
        {"id": "vllm", "label": "vLLM", "port": 8000},
        {"id": "llamacpp", "label": "llama.cpp", "port": llama_port},
    ]
    engines = []
    for probe in probes:
        status = probe_openai_models(f"http://127.0.0.1:{probe['port']}/v1/models")
        engines.append({**probe, **status})
    primary = next((e for e in engines if e["up"]), None)
    gateway = probe_openai_models(f"http://127.0.0.1:{GATEWAY_PORT}/v1/models")
    return {
        "up": primary is not None,
        "model": primary["model"] if primary else None,
        "engine": primary["id"] if primary else None,
        "engines": engines,
        "gateway": {
            "port": GATEWAY_PORT,
            "path": "/v1",
            "url": f"http://{SPARK_HOST}:{GATEWAY_PORT}/v1",
            "local_url": f"http://127.0.0.1:{GATEWAY_PORT}/v1",
            **gateway,
        },
    }"""

if '"gateway"' not in text.split("def read_inference", 1)[1].split("def append_history", 1)[0]:
    text = text.replace(old_read_inference, new_read_inference, 1)

old_metrics = """    metrics["containers"] = read_docker()
    containers = metrics["containers"]
    metrics["hermes"] = read_hermes_status(containers)
    metrics["inference"] = read_inference()
    metrics["history"] = append_history(metrics)"""

new_metrics = """    containers = read_docker()
    metrics["hermes"] = read_hermes_status(containers)
    metrics["inference"] = read_inference()
    metrics["containers"] = enrich_containers(containers, metrics["inference"])
    metrics["history"] = append_history(metrics)"""

if "metrics[\"containers\"] = enrich_containers" not in text:
    text = text.replace(old_metrics, new_metrics, 1)

path.write_text(text)
print("patched spark-gpu-metrics")
