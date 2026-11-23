#!/usr/bin/env bash
# k3s-node-resources.sh
# Shows CPU and RAM per k3s node: total capacity, allocatable, requested and limits
# (from pod specs), and live usage (from metrics-server).
#
# Usage:
#   ./k3s-node-resources.sh             # all nodes
#   ./k3s-node-resources.sh <node-name> # one node

set -euo pipefail

# ---------- pick kubectl ----------
if command -v kubectl >/dev/null 2>&1; then
  KUBECTL="kubectl"
elif command -v k3s >/dev/null 2>&1; then
  KUBECTL="k3s kubectl"
else
  echo "Error: neither kubectl nor k3s found in PATH" >&2
  exit 1
fi

# On a k3s server, kubeconfig lives here if not set
if [[ -z "${KUBECONFIG:-}" && -r /etc/rancher/k3s/k3s.yaml ]]; then
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
fi

# ---------- unit helpers ----------
# CPU quantity -> millicores (e.g. "4" -> 4000, "250m" -> 250)
cpu_to_m() {
  awk -v v="$1" 'BEGIN{
    n=v; sub(/[a-zA-Z]+$/,"",n); u=v; sub(/^[0-9.]+/,"",u)
    if (u=="n") printf "%d", n/1000000
    else if (u=="u") printf "%d", n/1000
    else if (u=="m") printf "%d", n
    else printf "%d", n*1000
  }'
}

# Memory quantity -> MiB (e.g. "8023456Ki" -> 7835, "2Gi" -> 2048)
mem_to_mi() {
  awk -v v="$1" 'BEGIN{
    n=v; sub(/[a-zA-Z]+$/,"",n); u=v; sub(/^[0-9.]+/,"",u)
    f["Ki"]=1/1024; f["Mi"]=1; f["Gi"]=1024; f["Ti"]=1048576
    f["k"]=1000/1048576; f["K"]=1000/1048576; f["M"]=1e6/1048576
    f["G"]=1e9/1048576; f["T"]=1e12/1048576; f[""]=1/1048576
    printf "%d", n*f[u]
  }'
}

fmt_cpu() { awk -v m="$1" 'BEGIN{printf "%.2f cores", m/1000}'; }
fmt_mem() { awk -v m="$1" 'BEGIN{printf "%.2f GiB", m/1024}'; }
pct()     { awk -v a="$1" -v b="$2" 'BEGIN{ if (b>0) printf "%.1f%%", a*100/b; else print "n/a" }'; }

# ---------- node list ----------
if [[ $# -gt 0 ]]; then
  NODES="$1"
else
  NODES=$($KUBECTL get nodes -o jsonpath='{.items[*].metadata.name}')
fi

# cluster totals
T_CAP_CPU=0; T_CAP_MEM=0; T_ALLOC_CPU=0; T_ALLOC_MEM=0
T_REQ_CPU=0; T_REQ_MEM=0; T_USED_CPU=0; T_USED_MEM=0
METRICS_OK=1
COUNT=0

for node in $NODES; do
  COUNT=$((COUNT + 1))

  # Capacity and allocatable
  read -r cap_cpu cap_mem alloc_cpu alloc_mem < <(
    $KUBECTL get node "$node" -o jsonpath='{.status.capacity.cpu} {.status.capacity.memory} {.status.allocatable.cpu} {.status.allocatable.memory}'
  ) || true
  cap_cpu_m=$(cpu_to_m "$cap_cpu");     cap_mem_mi=$(mem_to_mi "$cap_mem")
  alloc_cpu_m=$(cpu_to_m "$alloc_cpu"); alloc_mem_mi=$(mem_to_mi "$alloc_mem")

  # Requests / limits from "Allocated resources" in describe
  desc=$($KUBECTL describe node "$node")
  read -r req_cpu lim_cpu < <(awk '/Allocated resources:/{f=1} f && $1=="cpu"{print $2, $4; exit}' <<<"$desc")
  read -r req_mem lim_mem < <(awk '/Allocated resources:/{f=1} f && $1=="memory"{print $2, $4; exit}' <<<"$desc")
  req_cpu_m=$(cpu_to_m "${req_cpu:-0}");  lim_cpu_m=$(cpu_to_m "${lim_cpu:-0}")
  req_mem_mi=$(mem_to_mi "${req_mem:-0}"); lim_mem_mi=$(mem_to_mi "${lim_mem:-0}")

  # Live usage (needs metrics-server)
  top_line=$($KUBECTL top node "$node" --no-headers 2>/dev/null || true)
  if [[ -n "$top_line" ]]; then
    used_cpu_m=$(cpu_to_m "$(awk '{print $2}' <<<"$top_line")")
    used_mem_mi=$(mem_to_mi "$(awk '{print $4}' <<<"$top_line")")
    used_cpu_str="$(fmt_cpu "$used_cpu_m") ($(pct "$used_cpu_m" "$alloc_cpu_m"))"
    used_mem_str="$(fmt_mem "$used_mem_mi") ($(pct "$used_mem_mi" "$alloc_mem_mi"))"
    free_cpu_str=$(fmt_cpu $((alloc_cpu_m - used_cpu_m)))
    free_mem_str=$(fmt_mem $((alloc_mem_mi - used_mem_mi)))
  else
    METRICS_OK=0
    used_cpu_m=0; used_mem_mi=0
    used_cpu_str="n/a (metrics-server?)"; used_mem_str="n/a (metrics-server?)"
    free_cpu_str="n/a"; free_mem_str="n/a"
  fi

  # Print node report
  echo "=================================================================="
  echo " Node: $node"
  echo "=================================================================="
  printf "%-14s %-26s %-26s %s\n" "" "CPU" "MEMORY" "WHAT IT MEANS"
  printf "%-14s %-26s %-26s %s\n" "Total"       "$(fmt_cpu "$cap_cpu_m")"   "$(fmt_mem "$cap_mem_mi")" \
    "Physical capacity of the node"
  printf "%-14s %-26s %-26s %s\n" "Allocatable" "$(fmt_cpu "$alloc_cpu_m")" "$(fmt_mem "$alloc_mem_mi")" \
    "Capacity schedulable to pods (Total minus system/kubelet reserved)"
  printf "%-14s %-26s %-26s %s\n" "Requested" \
    "$(fmt_cpu "$req_cpu_m") ($(pct "$req_cpu_m" "$alloc_cpu_m"))" \
    "$(fmt_mem "$req_mem_mi") ($(pct "$req_mem_mi" "$alloc_mem_mi"))" \
    "Reserved by pod requests; drives scheduling (% of Allocatable)"
  printf "%-14s %-26s %-26s %s\n" "Limits" \
    "$(fmt_cpu "$lim_cpu_m") ($(pct "$lim_cpu_m" "$alloc_cpu_m"))" \
    "$(fmt_mem "$lim_mem_mi") ($(pct "$lim_mem_mi" "$alloc_mem_mi"))" \
    "Max pods may consume; >100% = overcommitted"
  printf "%-14s %-26s %-26s %s\n" "Used (live)" "$used_cpu_str" "$used_mem_str" \
    "Actual real-time usage (from metrics-server)"
  printf "%-14s %-26s %-26s %s\n" "Free (live)" "$free_cpu_str" "$free_mem_str" \
    "Allocatable minus live usage (remaining headroom)"
  echo

  # Accumulate totals
  T_CAP_CPU=$((T_CAP_CPU + cap_cpu_m));       T_CAP_MEM=$((T_CAP_MEM + cap_mem_mi))
  T_ALLOC_CPU=$((T_ALLOC_CPU + alloc_cpu_m)); T_ALLOC_MEM=$((T_ALLOC_MEM + alloc_mem_mi))
  T_REQ_CPU=$((T_REQ_CPU + req_cpu_m));       T_REQ_MEM=$((T_REQ_MEM + req_mem_mi))
  T_USED_CPU=$((T_USED_CPU + used_cpu_m));    T_USED_MEM=$((T_USED_MEM + used_mem_mi))
done

# Cluster summary when more than one node
if (( COUNT > 1 )); then
  echo "=================================================================="
  echo " Cluster total ($COUNT nodes)"
  echo "=================================================================="
  printf "%-14s %-26s %-26s\n" "" "CPU" "MEMORY"
  printf "%-14s %-26s %-26s\n" "Total"       "$(fmt_cpu "$T_CAP_CPU")"   "$(fmt_mem "$T_CAP_MEM")"
  printf "%-14s %-26s %-26s\n" "Allocatable" "$(fmt_cpu "$T_ALLOC_CPU")" "$(fmt_mem "$T_ALLOC_MEM")"
  printf "%-14s %-26s %-26s\n" "Requested" \
    "$(fmt_cpu "$T_REQ_CPU") ($(pct "$T_REQ_CPU" "$T_ALLOC_CPU"))" \
    "$(fmt_mem "$T_REQ_MEM") ($(pct "$T_REQ_MEM" "$T_ALLOC_MEM"))"
  if (( METRICS_OK )); then
    printf "%-14s %-26s %-26s\n" "Used (live)" \
      "$(fmt_cpu "$T_USED_CPU") ($(pct "$T_USED_CPU" "$T_ALLOC_CPU"))" \
      "$(fmt_mem "$T_USED_MEM") ($(pct "$T_USED_MEM" "$T_ALLOC_MEM"))"
  fi
fi