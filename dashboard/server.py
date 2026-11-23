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
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
SSH_CONFIG = BASE_DIR / "ssh-nodes.json"
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
# host-level usage over SSH  (processes + containers OUTSIDE kubernetes)
# ----------------------------------------------------------------------------
# One remote command emits delimited sections we parse below.
_REMOTE_CMD = r'''
echo "###LOAD"; uptime
echo "###MEM"; free -m | awk 'NR==2{printf "%s %s %s\n",$2,$3,$4}'
C=$(ps -eo pid,pcpu,pmem,rss,user,args --sort=-pcpu | sed -n '2,16p')
R=$(ps -eo pid,pmem,pcpu,rss,user,args --sort=-pmem | sed -n '2,16p')
echo "###CPU"; printf '%s\n' "$C"
echo "###RAM"; printf '%s\n' "$R"
PIDS=$( { printf '%s\n' "$C"; printf '%s\n' "$R"; } | awk '{print $1}' | sort -u | tr '\n' ' ')
DCMD='for pid in '"$PIDS"'; do printf "%s|%s|%s|%s\n" "$pid" "$(readlink /proc/$pid/cwd 2>/dev/null)" "$(readlink /proc/$pid/exe 2>/dev/null)" "$(cat /proc/$pid/cgroup 2>/dev/null | tr "\n" ",")"; done'
echo "###DETAIL"
if sudo -n true 2>/dev/null; then sudo -n bash -c "$DCMD"; else bash -c "$DCMD"; fi
echo "###CMAP"
if command -v docker >/dev/null 2>&1; then
  { timeout 6 docker ps --no-trunc --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null; timeout 6 sudo -n docker ps --no-trunc --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null; } | awk '!seen[$0]++' | head -80
fi
echo "###CONTAINERS"
fmt='{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}'
if command -v docker >/dev/null 2>&1; then
  if timeout 6 docker ps >/dev/null 2>&1; then
    timeout 7 docker stats --no-stream --format "$fmt" 2>/dev/null | head -n 30
  elif timeout 6 sudo -n docker ps >/dev/null 2>&1; then
    timeout 7 sudo -n docker stats --no-stream --format "$fmt" 2>/dev/null | head -n 30
  fi
fi
echo "###END"
'''


def load_ssh_config():
    try:
        raw = json.loads(SSH_CONFIG.read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def _guess_project(cmd):
    """Best-effort: the first absolute filesystem path in the command line."""
    for tok in cmd.split()[1:]:
        if tok.startswith("/") and "://" not in tok:
            return tok
    return ""


def _proc(line, cpu_first, detail_map, cmap):
    f = line.split(None, 5)
    if len(f) < 6:
        return None
    pid = f[0]
    a, b = float(f[1]), float(f[2])
    cpu, mem = (a, b) if cpu_first else (b, a)
    cmd = f[5]
    short = cmd.split()[0].split("/")[-1] if cmd else ""
    d = detail_map.get(pid, {})
    cwd, exe, cid = d.get("cwd", ""), d.get("exe", ""), d.get("cid", "")
    cont = cmap.get(cid, {}) if cid else {}
    # "where the file lives" — prefer exe dir / cwd / a path in the command line
    location = cwd or (exe.rsplit("/", 1)[0] if "/" in exe else "") or _guess_project(cmd)
    return {"pid": pid, "cpu": cpu, "mem": mem, "rssMi": round(int(f[3]) / 1024, 1),
            "user": f[4], "comm": short, "cmd": cmd,
            "cwd": cwd, "exe": exe, "location": location,
            "container": cont.get("name", ""), "image": cont.get("image", ""),
            "project": cont.get("name") or location or _guess_project(cmd)}


def parse_host_usage(out):
    sect, buckets = None, {"LOAD": [], "MEM": [], "CPU": [], "RAM": [],
                           "DETAIL": [], "CMAP": [], "CONTAINERS": []}
    for line in out.splitlines():
        if line.startswith("###"):
            sect = line[3:].strip()
            continue
        if sect in buckets and line.strip():
            buckets[sect].append(line)

    # container id -> {name, image}
    cmap = {}
    for line in buckets["CMAP"]:
        p = line.split("|")
        if len(p) == 3:
            cmap[p[0]] = {"name": p[1], "image": p[2]}

    # pid -> {cwd, exe, cid}
    detail_map = {}
    for line in buckets["DETAIL"]:
        p = line.split("|")
        if len(p) >= 4:
            cg = p[3]
            m = re.search(r"docker[-/]([0-9a-f]{12,64})", cg)
            cid = ""
            if m:
                full = m.group(1)
                cid = next((k for k in cmap if k.startswith(full) or full.startswith(k)), full)
            detail_map[p[0].strip()] = {"cwd": p[1].strip(), "exe": p[2].strip(), "cid": cid}

    load = buckets["LOAD"][0] if buckets["LOAD"] else ""
    m = re.search(r"load average[s]?:\s*([\d.]+)", load)
    load1 = float(m.group(1)) if m else None

    mem = {}
    if buckets["MEM"]:
        p = buckets["MEM"][0].split()
        if len(p) == 3:
            mem = {"total_mi": int(p[0]), "used_mi": int(p[1]), "free_mi": int(p[2])}

    containers = []
    for line in buckets["CONTAINERS"]:
        parts = line.split("|")
        if len(parts) == 3 and parts[0] not in ("", "--") and parts[1] != "--":
            containers.append({"name": parts[0], "cpu": parts[1], "mem": parts[2]})

    return {
        "load1": load1,
        "mem": mem,
        "procsByCpu": [p for p in (_proc(l, True, detail_map, cmap) for l in buckets["CPU"]) if p],
        "procsByMem": [p for p in (_proc(l, False, detail_map, cmap) for l in buckets["RAM"]) if p],
        "containers": containers,
    }


def get_host_usage(name, cfg):
    opts = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new"]

    alias = cfg.get("alias")
    if alias:
        # Use an ~/.ssh/config Host alias — it carries host/port/user/key.
        target = alias if isinstance(alias, str) and alias else name
    else:
        user = cfg.get("user", "")
        host = cfg.get("host", "")
        if not host or user in ("", "USER"):
            return {"name": name, "ok": False,
                    "error": "not configured — set an ssh-config alias, or user/host, in ssh-nodes.json"}
        key = cfg.get("key")
        if key:
            opts += ["-i", os.path.expanduser(f"~/.ssh/{key}")]
        port = cfg.get("port", 22)
        if port and int(port) != 22:
            opts += ["-p", str(port)]
        target = f"{user}@{host}"
    opts += [target, _REMOTE_CMD]

    try:
        res = subprocess.run(opts, capture_output=True, text=True, timeout=55)
    except subprocess.TimeoutExpired:
        return {"name": name, "ok": False, "error": "SSH timed out (unreachable? wrong port? remote command hung?)"}
    if res.returncode != 0 or "###END" not in res.stdout:
        err = (res.stderr or res.stdout or "ssh failed").strip().splitlines()
        return {"name": name, "ok": False, "error": (err[-1] if err else "ssh failed")[:200]}

    data = parse_host_usage(res.stdout)
    data.update({"name": name, "ok": True})
    return data


def build_processes(node):
    cfg = load_ssh_config()
    names = [n for n in cfg if not n.startswith("_")]
    if node and node != "all":
        names = [node] if node in names else []
    if not names:
        return {"nodes": [], "configured": False,
                "error": "No nodes configured. Edit ssh-nodes.json (set the SSH user/key)."}
    return {"nodes": [get_host_usage(n, cfg[n]) for n in names], "configured": True}


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

        if path == "/api/processes":
            node = (parse_qs(urlparse(self.path).query).get("node") or ["all"])[0]
            try:
                self._send(200, build_processes(node))
            except Exception as e:
                self._send(200, {"nodes": [], "error": f"{type(e).__name__}: {e}"})
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
