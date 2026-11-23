#!/usr/bin/env bash
# Launch the k3s dashboard. Run this inside WSL and keep the terminal open.
#   ./run.sh            # http://localhost:8787
#   ./run.sh 9000       # custom port
cd "$(dirname "$0")"
exec python3 server.py "${1:-8787}"
