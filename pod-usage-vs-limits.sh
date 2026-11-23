#!/usr/bin/env bash
# pod-usage-vs-limits.sh
# Shows, per pod on a node: live CPU/MEM usage next to its requests and limits.
# Usage: ./pod-usage-vs-limits.sh <node-name>   (defaults to the first node)

set -uo pipefail

NODE="${1:-$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')}"

# live usage keyed by namespace/name: key cpu mem
usage=$(kubectl top pods -A --no-headers | awk '{print $1"/"$2, $3, $4}' | sort -k1,1)

# spec keyed by namespace/name: key cpu_req cpu_lim mem_req mem_lim (only pods on this node)
spec=$(kubectl get pods -A --field-selector "spec.nodeName=$NODE" --no-headers \
  -o custom-columns=':.metadata.namespace,:metadata.name,:.spec.containers[*].resources.requests.cpu,:.spec.containers[*].resources.limits.cpu,:.spec.containers[*].resources.requests.memory,:.spec.containers[*].resources.limits.memory' \
  | awk '{print $1"/"$2, $3, $4, $5, $6}' | sort -k1,1)

FMT="%-22s %-46s %-9s %-9s %-9s %-9s %-9s %-9s\n"
printf "$FMT" NAMESPACE POD CPU_USE CPU_REQ CPU_LIM MEM_USE MEM_REQ MEM_LIM
join -1 1 -2 1 <(echo "$usage") <(echo "$spec") \
  | awk -v fmt="%-22s %-46s %-9s %-9s %-9s %-9s %-9s %-9s\n" \
      '{for(i=1;i<=NF;i++) if($i=="<none>") $i="not-set";
        n=index($1,"/"); ns=substr($1,1,n-1); pod=substr($1,n+1);
        printf fmt, ns, pod, $2, $4, $5, $3, $6, $7}' \
  | sort -k6 -h -r
