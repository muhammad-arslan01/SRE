#!/usr/bin/env bash
# node-host-usage.sh
# SSHes into each node and shows the TOP host processes and containers by
# CPU / RAM — including everything running OUTSIDE Kubernetes (which
# `kubectl top` cannot see).
#
#   ./node-host-usage.sh              # all nodes below
#   ./node-host-usage.sh k3s-master  # one node
#
# EDIT the NODES map: "alias=user@host[:port]|keyfile"
# (keyfile is relative to ~/.ssh ; leave blank to use ssh defaults/agent)

declare -A NODES=(
  [db-cloud]="USER@100.116.175.108|production-node-1"
  [devserver]="USER@100.90.161.119|production-node-1"
  [k3s-master]="root@100.109.216.94|k3s-master-prod"
  # [meissasoft-server]="USER@HOST:PORT|prod-node-1"   # :22 unreachable — set real host/port
)

TOPN="${TOPN:-12}"

ssh_run() {  # $1=target  $2=key  $3=remote command
  local target="$1" key="$2" cmd="$3" opts
  opts=(-o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
  [ -n "$key" ] && opts+=(-i "$HOME/.ssh/$key")
  ssh "${opts[@]}" "$target" "$cmd" 2>&1
}

report_node() {
  local name="$1" spec="${NODES[$1]}"
  local conn="${spec%%|*}" key="${spec##*|}"
  [ "$key" = "$conn" ] && key=""
  local host="${conn#*@}"; host="${host%%:*}"
  local port=""; [[ "$conn" == *:* ]] && port="-p ${conn##*:}"
  local target="${conn%%:*}"

  echo "=================================================================="
  echo " Node: $name   ($conn)"
  echo "=================================================================="
  if ! ssh_run "$target" "$key" "true" >/dev/null; then
    echo "  !! cannot SSH (fix USER/key/port in the NODES map)"; echo; return
  fi

  echo "-- load / memory --"
  ssh_run "$target" "$key" "uptime; echo; free -h | head -2"
  echo
  echo "-- top $TOPN processes by CPU --"
  ssh_run "$target" "$key" "ps -eo pcpu,pmem,rss,user,comm --sort=-pcpu | head -n $((TOPN+1))"
  echo
  echo "-- top $TOPN processes by RAM --"
  ssh_run "$target" "$key" "ps -eo pmem,pcpu,rss,user,comm --sort=-pmem | head -n $((TOPN+1))"
  echo
  echo "-- containers (auto-detect docker / k3s-containerd) --"
  ssh_run "$target" "$key" '
    if command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
      echo "[docker stats]"; docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" | head -n 20
    else echo "(no usable docker daemon)"; fi
    echo
    if command -v crictl >/dev/null 2>&1; then
      echo "[crictl ps — k3s/containerd]"; crictl ps -o table 2>/dev/null | head -n 20
    elif [ -S /run/k3s/containerd/containerd.sock ]; then
      echo "[crictl via k3s sock]"; crictl --runtime-endpoint unix:///run/k3s/containerd/containerd.sock ps 2>/dev/null | head -n 20
    else echo "(no crictl)"; fi'
  echo
}

targets=("$@"); [ ${#targets[@]} -eq 0 ] && targets=("${!NODES[@]}")
for n in "${targets[@]}"; do
  [ -n "${NODES[$n]:-}" ] && report_node "$n" || echo "unknown node: $n"
done
