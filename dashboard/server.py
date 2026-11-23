#!/usr/bin/env python3
"""
k3s resource dashboard — backend + static server.

Runs inside WSL (where kubectl works), serves a React frontend and a small
JSON API. WSL2 forwards localhost to Windows, so once this is running you can
open http://localhost:8787 in a Windows browser.

    python3 server.py            # port 8787
    python3 server.py 9000       # custom port

No third-party dependencies — Python standard library only.
"""

import json
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

WEB_DIR = Path(__file__).resolve().parent / "web"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787


# ----------------------------------------------------------------------------
# kubectl helpers
# ----------------------------------------------------------------------------
def kubectl(*args, parse_json=False):
    """Run a kubectl command. Returns parsed JSON, text, or None on failure."""
    try:
        out = subprocess.run(
            ["kubectl", *args],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return json.loads(out) if parse_json else out


# ----------------------------------------------------------------------------
# unit parsing  (-> CPU in millicores, memory in MiB)
# ----------------------------------------------------------------------------
def cpu_to_m(q):
    if not q or q in ("<none>", "0"):
        return 0.0
    m = re.match(r"^([0-9.]+)([a-zA-Z]*)$", str(q).strip())
    if not m:
        return 0.0
    n, unit = float(m.group(1)), m.group(2)
    return {"n": n / 1e6, "u": n / 1e3, "m": n}.get(unit, n * 1000)


_MEM_FACTORS = {
    "Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024, "Pi": 1024 ** 3,
    "k": 1000 / 1048576, "K": 1000 / 1048576, "M": 1e6 / 1048576,
    "G": 1e9 / 1048576, "T": 1e12 / 1048576, "": 1 / 1048576,
}


def mem_to_mi(q):
    if not q or q in ("<none>", "0"):
        return 0.0
    m = re.match(r"^([0-9.]+)([a-zA-Z]*)$", str(q).strip())
    if not m:
        return 0.0
    return float(m.group(1)) * _MEM_FACTORS.get(m.group(2), 1 / 1048576)


# ----------------------------------------------------------------------------
# build the snapshot the frontend consumes
# ----------------------------------------------------------------------------
def parse_top_nodes():
    """name -> {cpu_m, mem_mi} from `kubectl top nodes`."""
    out = kubectl("top", "nodes", "--no-headers")
    usage = {}
    if not out:
        return usage
    for line in out.strip().splitlines():
        f = line.split()
        if len(f) >= 5:
            usage[f[0]] = {"cpu_m": cpu_to_m(f[1]), "mem_mi": mem_to_mi(f[3])}
    return usage


def parse_top_pods():
    """'ns/name' -> {cpu_m, mem_mi} from `kubectl top pods -A`."""
    out = kubectl("top", "pods", "-A", "--no-headers")
    usage = {}
    if not out:
        return usage
    for line in out.strip().splitlines():
        f = line.split()
        if len(f) >= 4:
            usage[f[0] + "/" + f[1]] = {"cpu_m": cpu_to_m(f[2]), "mem_mi": mem_to_mi(f[3])}
    return usage


def container_totals(containers, field):
    """Sum requests/limits ('requests' or 'limits') across a pod's containers."""
    cpu = mem = 0.0
    has_cpu = has_mem = False
    for c in containers or []:
        res = (c.get("resources") or {}).get(field) or {}
        if "cpu" in res:
            cpu += cpu_to_m(res["cpu"]); has_cpu = True
        if "memory" in res:
            mem += mem_to_mi(res["memory"]); has_mem = True
    return cpu, mem, has_cpu, has_mem


def build_snapshot():
    nodes_json = kubectl("get", "nodes", "-o", "json", parse_json=True)
    pods_json = kubectl("get", "pods", "-A", "-o", "json", parse_json=True)
    if nodes_json is None or pods_json is None:
        return {"error": "kubectl could not reach the cluster. Check KUBECONFIG / connectivity."}

    node_use = parse_top_nodes()
    pod_use = parse_top_pods()
    metrics_ok = bool(node_use)

    # --- per node skeleton ---
    nodes = {}
    for n in nodes_json["items"]:
        name = n["metadata"]["name"]
        cap = n["status"].get("capacity", {})
        alloc = n["status"].get("allocatable", {})
        nodes[name] = {
            "name": name,
            "capacity": {"cpu_m": cpu_to_m(cap.get("cpu")), "mem_mi": mem_to_mi(cap.get("memory"))},
            "allocatable": {"cpu_m": cpu_to_m(alloc.get("cpu")), "mem_mi": mem_to_mi(alloc.get("memory"))},
            "requested": {"cpu_m": 0.0, "mem_mi": 0.0},
            "limits": {"cpu_m": 0.0, "mem_mi": 0.0},
            "used": node_use.get(name, {"cpu_m": 0.0, "mem_mi": 0.0}),
            "hasMetrics": name in node_use,
            "podCount": 0,
        }

    # --- pods, and accumulate node requests/limits ---
    pods = []
    for p in pods_json["items"]:
        phase = p.get("status", {}).get("phase", "")
        if phase in ("Succeeded", "Failed"):
            continue  # terminated pods don't hold resources
        ns = p["metadata"]["namespace"]
        name = p["metadata"]["name"]
        node = p.get("spec", {}).get("nodeName")
        containers = p.get("spec", {}).get("containers", [])

        req_cpu, req_mem, hrc, hrm = container_totals(containers, "requests")
        lim_cpu, lim_mem, hlc, hlm = container_totals(containers, "limits")
        use = pod_use.get(ns + "/" + name, {})

        pods.append({
            "namespace": ns, "name": name, "node": node, "phase": phase,
            "cpuUse_m": use.get("cpu_m"), "memUse_mi": use.get("mem_mi"),
            "cpuReq_m": req_cpu if hrc else None,
            "cpuLim_m": lim_cpu if hlc else None,
            "memReq_mi": req_mem if hrm else None,
            "memLim_mi": lim_mem if hlm else None,
        })

        if node in nodes:
            nodes[node]["requested"]["cpu_m"] += req_cpu
            nodes[node]["requested"]["mem_mi"] += req_mem
            nodes[node]["limits"]["cpu_m"] += lim_cpu
            nodes[node]["limits"]["mem_mi"] += lim_mem
            nodes[node]["podCount"] += 1

    node_list = sorted(nodes.values(), key=lambda x: x["name"])

    def agg(key, sub):
        return sum(n[key][sub] for n in node_list)

    cluster = {
        "nodeCount": len(node_list),
        "capacity": {"cpu_m": agg("capacity", "cpu_m"), "mem_mi": agg("capacity", "mem_mi")},
        "allocatable": {"cpu_m": agg("allocatable", "cpu_m"), "mem_mi": agg("allocatable", "mem_mi")},
        "requested": {"cpu_m": agg("requested", "cpu_m"), "mem_mi": agg("requested", "mem_mi")},
        "limits": {"cpu_m": agg("limits", "cpu_m"), "mem_mi": agg("limits", "mem_mi")},
        "used": {"cpu_m": agg("used", "cpu_m"), "mem_mi": agg("used", "mem_mi")},
        "podCount": sum(n["podCount"] for n in node_list),
    }

    return {"nodes": node_list, "pods": pods, "cluster": cluster, "metricsOk": metrics_ok}


# ----------------------------------------------------------------------------
# HTTP server
# ----------------------------------------------------------------------------
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".jsx": "text/babel; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep console quiet
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/data":
            try:
                self._send(200, build_snapshot())
            except Exception as e:  # never 500 silently
                self._send(200, {"error": f"{type(e).__name__}: {e}"})
            return

        # static files out of web/
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR not in target.parents and target != WEB_DIR or not target.is_file():
            self._send(404, {"error": "not found"})
            return
        ctype = _CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)


def main():
    if not WEB_DIR.is_dir():
        print(f"web/ not found at {WEB_DIR}", file=sys.stderr)
        sys.exit(1)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"k3s dashboard running  ->  http://localhost:{PORT}")
    print("(open that in your Windows browser; Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
