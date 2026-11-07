#!/usr/bin/env bash
# Zero-downtime check: run load.sh against the app while killing its pods, then report
# whether any request failed. Exercises preStop sleep, readiness probes, the PDB and
# rollingUpdate maxUnavailable: 0 on the kind smoke cluster.
# Usage: chaos.sh (<app-path> [overlay] | -n <namespace>) [options]
#   --kills N          disruptions to cause (default: 5)
#   --interval SECS    pause between disruptions (default: 10)
#   --mode M           delete  - kubectl delete a random ready pod (default)
#                      evict   - Eviction API on a random pod (honours the PDB)
#                      rollout - kubectl rollout restart (exercises maxUnavailable/maxSurge)
#   --max-error-rate R tolerated failure fraction (default: 0 = zero downtime)
#   --rps N            fixed request rate (default: 50); --vus N pre-allocated VUs (default: 10)
#   --deployment D, --service S, --path P, --timeout SECS  as in load.sh
# Exit: 0 no failed requests, 1 requests failed, 2 usage/setup error, 3 INCONCLUSIVE.
# Only talks to the kind-k8s-anything context, only to smoke-* namespaces.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib-kind.sh disable=SC1091
. "$HERE/lib-kind.sh"

NS="" APP="" OVERLAY="" DEPLOY="" SVC="" KILLS=5 INTERVAL=10 MODE=delete MAX_ERR=0
# Modest fixed-rate load: this measures availability, not capacity. Saturating the app
# (or a busy shared node) turns into timeouts that have nothing to do with restarts.
LOAD_ARGS=(--rps 50 --vus 10)
while [ $# -gt 0 ]; do
  case "$1" in
    -n|--namespace) NS="${2:?}"; shift 2;;
    --deployment) DEPLOY="${2:?}"; shift 2;;
    --service) SVC="${2:?}"; shift 2;;
    --kills) KILLS="${2:?}"; shift 2;;
    --interval) INTERVAL="${2:?}"; shift 2;;
    --mode) MODE="${2:?}"; shift 2;;
    --max-error-rate) MAX_ERR="${2:?}"; shift 2;;
    --path|--vus|--rps|--timeout) LOAD_ARGS+=("$1" "${2:?}"); shift 2;;
    -h|--help) sed -n '2,15p' "$0"; exit 0;;
    -*) die "unknown option: $1";;
    *) if [ -z "$APP" ]; then APP="$1"; elif [ -z "$OVERLAY" ]; then OVERLAY="$1"
       else die "unexpected argument: $1"; fi; shift;;
  esac
done
for v in "$KILLS" "$INTERVAL"; do
  case "$v" in ''|*[!0-9]*) die "--kills/--interval take whole numbers";; esac
done
case "$MODE" in delete|evict|rollout) ;; *) die "--mode must be delete, evict or rollout";; esac

resolve_target "$NS" "$APP" "$OVERLAY" "$DEPLOY" "$SVC"

# Names of Ready pods that aren't already terminating, one per line.
ready_pods() {
  # shellcheck disable=SC2016 # go-template, not shell
  "${K[@]}" -n "$NS" get pods -l "$SELECTOR" -o go-template='{{range $p := .items}}{{if not $p.metadata.deletionTimestamp}}{{range $p.status.conditions}}{{if and (eq .type "Ready") (eq .status "True")}}{{$p.metadata.name}}{{"\n"}}{{end}}{{end}}{{end}}{{end}}' 2>/dev/null || true
}
# Wait until the Deployment is fully rolled out and every desired replica is ready.
wait_stable() {
  local want n deadline=$(( $(date +%s) + 180 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    want="$("${K[@]}" -n "$NS" get deploy "$DEPLOY" -o jsonpath='{.spec.replicas}' 2>/dev/null || true)"
    n="$(ready_pods | grep -c . || true)"
    if [ -n "$want" ] && [ "$n" -ge "$want" ] \
      && "${K[@]}" -n "$NS" rollout status "deploy/$DEPLOY" --timeout=1s >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Deployment $DEPLOY did not become stable within 180s" >&2
  return 1
}
ts() { date -u +%H:%M:%SZ; }

wait_stable || exit 3
REPLICAS="$("${K[@]}" -n "$NS" get deploy "$DEPLOY" -o jsonpath='{.spec.replicas}')"
if [ "$MODE" != rollout ] && [ "${REPLICAS:-0}" -lt 2 ]; then
  die "$DEPLOY has $REPLICAS replica(s): killing a pod is downtime by definition. Use the prod overlay (HPA minReplicas >= 2), scale up, or --mode rollout."
fi

# Load runs for the whole experiment: warm-up, each disruption plus time for the
# Deployment to settle before the next, then time to recover. Disruptions that would
# land after the load ended are skipped and make the run INCONCLUSIVE.
DURATION=$(( 10 + KILLS * (INTERVAL + 20) + 30 ))
JOB="k8sa-chaos-$$-$RANDOM"
LOG="$(mktemp "${TMPDIR:-/tmp}/k8sa-chaos.XXXXXX")"
echo "== chaos: $KILLS x $MODE every ${INTERVAL}s on $NS/deploy/$DEPLOY ($REPLICAS replicas) under load (${DURATION}s)"
"$HERE/load.sh" -n "$NS" --deployment "$DEPLOY" --service "$SVC" --duration "$DURATION" \
  --max-error-rate "$MAX_ERR" --name "$JOB" ${LOAD_ARGS[@]+"${LOAD_ARGS[@]}"} >"$LOG" 2>&1 &
LOAD_PID=$!
# shellcheck disable=SC2329 # invoked by the EXIT trap
finish() {
  kill "$LOAD_PID" 2>/dev/null || true
  rm -f "$LOG"
  "${K[@]}" -n "$NS" delete job,configmap "$JOB" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap finish EXIT

# Start disrupting only once the load pod is actually sending traffic.
for _ in $(seq 1 60); do
  phase="$("${K[@]}" -n "$NS" get pods -l "k8sa-load-job=$JOB" -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
  [ "$phase" = Running ] && break
  kill -0 "$LOAD_PID" 2>/dev/null || break
  sleep 2
done
[ "$phase" = Running ] || { cat "$LOG" >&2; echo "INCONCLUSIVE: load pod never started" >&2; exit 3; }
sleep 10

i=0
DONE=0
while [ "$i" -lt "$KILLS" ]; do
  i=$((i + 1))
  wait_stable || break
  kill -0 "$LOAD_PID" 2>/dev/null || { echo "load finished before disruption $i; stopping"; break; }
  case "$MODE" in
    rollout)
      echo "$(ts) [$i/$KILLS] rollout restart deploy/$DEPLOY"
      "${K[@]}" -n "$NS" rollout restart "deploy/$DEPLOY" >/dev/null || break
      "${K[@]}" -n "$NS" rollout status "deploy/$DEPLOY" --timeout=180s >/dev/null \
        || { echo "rollout did not finish in 180s; stopping" >&2; break; };;
    *)
      # shellcheck disable=SC2207
      pods=($(ready_pods))
      [ "${#pods[@]}" -gt 0 ] || { echo "no ready pods" >&2; break; }
      pod="${pods[$((RANDOM % ${#pods[@]}))]}"
      if [ "$MODE" = delete ]; then
        echo "$(ts) [$i/$KILLS] delete pod $pod"
        "${K[@]}" -n "$NS" delete pod "$pod" --wait=false >/dev/null || break
      else
        echo "$(ts) [$i/$KILLS] evict pod $pod"
        evicted=""
        for _ in $(seq 1 20); do   # 429 = PDB says not now; retry
          if printf '{"apiVersion":"policy/v1","kind":"Eviction","metadata":{"name":"%s","namespace":"%s"}}' "$pod" "$NS" \
            | "${K[@]}" create --raw "/api/v1/namespaces/$NS/pods/$pod/eviction" -f - >/dev/null 2>&1; then
            evicted=1; break
          fi
          echo "  eviction refused (PDB), retrying"; sleep 3
        done
        [ -n "$evicted" ] || { echo "eviction kept being refused; stopping" >&2; break; }
      fi;;
  esac
  DONE=$i
  sleep "$INTERVAL"
done

set +e
wait "$LOAD_PID"; rc=$?
set -e
cat "$LOG"
if [ "$rc" -eq 0 ] && [ "$DONE" -lt "$KILLS" ]; then
  echo "INCONCLUSIVE: only $DONE of $KILLS disruptions happened under load (cluster too slow?)"
  rc=3
elif [ "$rc" -eq 0 ]; then
  echo "ZERO-DOWNTIME PASS: $DONE x $MODE on $DEPLOY, no requests failed beyond --max-error-rate $MAX_ERR"
elif [ "$rc" -eq 1 ]; then
  echo "ZERO-DOWNTIME FAIL: requests failed during $DONE x $MODE (see K8SA_FAIL lines above for timestamps)"
  echo "Check: preStop sleep, readinessProbe, graceful SIGTERM handling in the app server, PDB, maxUnavailable: 0."
else
  echo "INCONCLUSIVE: load test exited $rc"
fi
exit "$rc"
