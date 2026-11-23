# k3s Resource Dashboard

A small web dashboard that shows CPU/RAM per node and per pod (live usage vs.
requests vs. limits) for your k3s cluster.

- **Backend** (`server.py`) runs **in WSL**, where `kubectl` works. Pure Python
  standard library — no `pip install` needed.
- **Frontend** (`web/`) is a **React 18** app, rendered in your **Windows browser**.
  React is vendored under `web/vendor/` so it works offline.

WSL2 forwards `localhost` to Windows, so the Windows browser can reach the WSL
server directly.

## One-time setup
Vendors the React libraries (needs internet once):
```bash
./setup.sh
```

## Run
In a WSL terminal (keep it open while you use the dashboard):
```bash
./run.sh            # serves on http://localhost:8787
./run.sh 9000       # or a custom port
```
Then open **http://localhost:8787** in your Windows browser.

## What it shows
- **Cluster KPIs** — nodes, pods, CPU/mem allocatable and live usage.
- **Node cards** — per node, stacked bars for CPU and memory: live *used* over
  *requested* within *allocatable*, plus a *limit* marker (⚠ when limits
  overcommit the node).
- **Pod table** — every pod's live CPU/mem next to its requests and limits,
  with a *use ÷ limit* bar. Search by namespace/pod, filter by node, click any
  column header to sort. Unset values show as `not-set`.

Data auto-refreshes every 15s (toggle in the header) or on the Refresh button.

## Files
| File | Purpose |
|------|---------|
| `server.py` | kubectl → JSON API + static file server |
| `web/index.html` | page shell, loads React + the app |
| `web/app.jsx` | React components (cards, table, controls) |
| `web/styles.css` | styling |
| `web/vendor/` | React, ReactDOM, Babel (vendored) |
| `setup.sh` | downloads the vendored libraries |
| `run.sh` | launches the server |
| `selftest.sh` | prints the parsed snapshot without the browser |
