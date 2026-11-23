#!/usr/bin/env bash
cd "$(dirname "$0")"
python3 - <<'PY'
import json, server
snap = server.build_snapshot()
if "error" in snap:
    print("ERROR:", snap["error"]); raise SystemExit(1)
print("nodes:", len(snap["nodes"]), " pods:", len(snap["pods"]), " metricsOk:", snap["metricsOk"])
for n in snap["nodes"]:
    a = n["allocatable"]; u = n["used"]; l = n["limits"]
    print(f"  {n['name']:<20} alloc {a['cpu_m']/1000:.0f}c/{a['mem_mi']/1024:.1f}Gi "
          f"used {u['cpu_m']/1000:.2f}c/{u['mem_mi']/1024:.1f}Gi "
          f"limMem {l['mem_mi']/1024:.1f}Gi  pods={n['podCount']}")
p = snap["pods"][0]
print("sample pod keys:", sorted(p.keys()))
PY
