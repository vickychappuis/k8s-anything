#!/usr/bin/env bash
# HTTP load test against an app deployed by smoke-kind.sh, run from inside the kind
# cluster as a Job (pinned grafana/k6 image), so it behaves the same on macOS and CI.
# Usage: load.sh (<app-path> [overlay] | -n <namespace>) [options]
#   --deployment D     app Deployment (default: the only one in the namespace)
#   --service S        Service to hit (default: same name as the Deployment)
#   --path P           URL path (default: /)
#   --vus N            concurrent virtual users (default: 10)
#   --rps N            fixed arrival rate instead of as-fast-as-possible VUs (default:
#                      0 = off); --vus is then the pre-allocated pool (max 5x)
#   --duration SECS    test length in seconds (default: 30)
#   --max-error-rate R fail above this fraction of failed requests (default: 0.01)
#   --timeout SECS     per-request timeout (default: 5)
#   --name NAME        Job name (default: k8sa-load-<random>)
# A request fails on a network error, a timeout or a status outside 200-399.
# Exit: 0 pass, 1 error rate above threshold, 2 usage/setup error, 3 no result
# (INCONCLUSIVE). Only talks to the kind-k8s-anything context, only to smoke-* namespaces.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib-kind.sh disable=SC1091
. "$HERE/lib-kind.sh"

K6_IMAGE="${K8SA_K6_IMAGE:-grafana/k6:0.54.0}"
NS="" APP="" OVERLAY="" DEPLOY="" SVC="" URL_PATH="/" VUS=10 RPS=0 DURATION=30
MAX_ERR="0.01" REQ_TIMEOUT=5 NAME="k8sa-load-$$-$RANDOM"
while [ $# -gt 0 ]; do
  case "$1" in
    -n|--namespace) NS="${2:?}"; shift 2;;
    --deployment) DEPLOY="${2:?}"; shift 2;;
    --service) SVC="${2:?}"; shift 2;;
    --path) URL_PATH="${2:?}"; shift 2;;
    --vus) VUS="${2:?}"; shift 2;;
    --duration) DURATION="${2:?}"; shift 2;;
    --max-error-rate) MAX_ERR="${2:?}"; shift 2;;
    --timeout) REQ_TIMEOUT="${2:?}"; shift 2;;
    --name) NAME="${2:?}"; shift 2;;
    --rps) RPS="${2:?}"; shift 2;;
    -h|--help) sed -n '2,17p' "$0"; exit 0;;
    -*) die "unknown option: $1";;
    *) if [ -z "$APP" ]; then APP="$1"; elif [ -z "$OVERLAY" ]; then OVERLAY="$1"
       else die "unexpected argument: $1"; fi; shift;;
  esac
done
for v in "$VUS" "$RPS" "$DURATION" "$REQ_TIMEOUT"; do
  case "$v" in ''|*[!0-9]*) die "--vus/--rps/--duration/--timeout take whole numbers";; esac
done
case "$URL_PATH" in /*) ;; *) URL_PATH="/$URL_PATH";; esac

resolve_target "$NS" "$APP" "$OVERLAY" "$DEPLOY" "$SVC"
TARGET="http://$SVC.$NS.svc:$SVC_PORT$URL_PATH"

cleanup() {
  "${K[@]}" -n "$NS" delete job "$NAME" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  "${K[@]}" -n "$NS" delete configmap "$NAME" --ignore-not-found >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 3' INT TERM

# The k6 script prints one machine-readable K8SA_RESULT line and the first few
# failures (per VU) with timestamps, so chaos.sh can line them up with pod kills.
# Failures are split into timeouts, connection errors (refused/reset/EOF) and bad
# HTTP statuses: a restart bug usually shows as conn/5xx, an overloaded node as timeouts.
"${K[@]}" -n "$NS" create configmap "$NAME" --dry-run=client -o yaml --from-literal=load.js='
import http from "k6/http";
import { Counter } from "k6/metrics";
const timeouts = new Counter("k8sa_timeout"), conns = new Counter("k8sa_conn"), bad = new Counter("k8sa_http");
const vus = Number(__ENV.VUS), rps = Number(__ENV.RPS), dur = __ENV.DURATION + "s";
export const options = Object.assign({
  discardResponseBodies: true,
  summaryTrendStats: ["med", "p(95)", "p(99)", "max"],
}, rps > 0 ? { scenarios: { load: {
  executor: "constant-arrival-rate", rate: rps, timeUnit: "1s", duration: dur,
  preAllocatedVUs: vus, maxVUs: vus * 5,
} } } : { vus: vus, duration: dur });
let logged = 0;
export default function () {
  const r = http.get(__ENV.TARGET, { timeout: __ENV.REQ_TIMEOUT + "s" });
  if (r.status >= 200 && r.status <= 399) return;
  if (r.status === 0 && /timeout/i.test(r.error || "")) timeouts.add(1);
  else if (r.status === 0) conns.add(1);
  else bad.add(1);
  if (logged < 3) {
    logged++;
    console.warn("K8SA_FAIL " + new Date().toISOString() + " status=" + r.status + " error=" + JSON.stringify(r.error || ""));
  }
}
export function handleSummary(d) {
  const m = d.metrics, lat = m.http_req_duration.values, f = m.http_req_failed.values;
  const n = (k) => (m[k] ? m[k].values.count : 0);
  const reqs = m.http_reqs.values.count, failed = f.passes;
  const line = "K8SA_RESULT requests=" + reqs + " failed=" + failed +
    " timeout=" + n("k8sa_timeout") + " conn=" + n("k8sa_conn") + " http=" + n("k8sa_http") +
    " dropped=" + n("dropped_iterations") +
    " error_rate=" + (reqs ? failed / reqs : 0).toFixed(4) +
    " rps=" + m.http_reqs.values.rate.toFixed(1) +
    " p50_ms=" + lat.med.toFixed(1) + " p95_ms=" + lat["p(95)"].toFixed(1) +
    " p99_ms=" + lat["p(99)"].toFixed(1) + " max_ms=" + lat.max.toFixed(1) + "\n";
  return { stdout: line };
}
' | "${K[@]}" apply -f - >/dev/null

# Restricted-PSA compliant (smoke namespaces enforce it). Runs in the app's namespace,
# so the prod overlay's "allow from same namespace" NetworkPolicy admits it.
"${K[@]}" -n "$NS" apply -f - >/dev/null <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $NAME
  labels: {app.kubernetes.io/name: k8sa-load, app.kubernetes.io/managed-by: k8s-anything}
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 600
  template:
    metadata:
      labels: {app.kubernetes.io/name: k8sa-load, k8sa-load-job: $NAME}
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 12345
        runAsGroup: 12345
        seccompProfile: {type: RuntimeDefault}
        # Apps that close every connection (gunicorn sync) leave one TIME_WAIT socket
        # per request on this side; at a few hundred rps the default ~28k ephemeral
        # ports run out ("cannot assign requested address"), which is a load-generator
        # failure, not app downtime. A "safe" sysctl, allowed under restricted PSA.
        sysctls:
          - {name: net.ipv4.ip_local_port_range, value: "1024 65535"}
      containers:
        - name: k6
          image: $K6_IMAGE
          imagePullPolicy: IfNotPresent
          args: ["run", "--quiet", "--no-color", "--no-usage-report", "/scripts/load.js"]
          env:
            - {name: TARGET, value: "$TARGET"}
            - {name: VUS, value: "$VUS"}
            - {name: RPS, value: "$RPS"}
            - {name: DURATION, value: "$DURATION"}
            - {name: REQ_TIMEOUT, value: "$REQ_TIMEOUT"}
            - {name: HOME, value: /tmp}
          resources:
            requests: {cpu: 200m, memory: 64Mi}
            limits: {memory: 512Mi}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          volumeMounts:
            - {name: scripts, mountPath: /scripts}
            - {name: tmp, mountPath: /tmp}
      volumes:
        - {name: scripts, configMap: {name: $NAME}}
        - {name: tmp, emptyDir: {}}
EOF

echo "== load: $VUS VUs (rps cap: ${RPS:-0}, 0 = none) for ${DURATION}s -> $TARGET (job $NS/$NAME, $K6_IMAGE)"
deadline=$(( $(date +%s) + DURATION + 180 ))
status=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  status="$("${K[@]}" -n "$NS" get job "$NAME" -o jsonpath='{.status.succeeded}/{.status.failed}' 2>/dev/null || true)"
  case "$status" in 1/*|*/1) break;; esac
  sleep 3
done
LOGS="$("${K[@]}" -n "$NS" logs "job/$NAME" 2>&1 || true)"
printf '%s\n' "$LOGS" | grep 'K8SA_FAIL' | head -20 || true
RESULT="$(printf '%s\n' "$LOGS" | grep '^K8SA_RESULT ' | tail -1 || true)"
if [ -z "$RESULT" ]; then
  echo "INCONCLUSIVE: load job produced no result (job status '$status'). Logs:" >&2
  printf '%s\n' "$LOGS" | tail -20 >&2
  "${K[@]}" -n "$NS" get pods -l "k8sa-load-job=$NAME" >&2 2>&1 || true
  exit 3
fi
echo "$RESULT"
printf '%s\n' "$RESULT" | awk -v max="$MAX_ERR" '{
  for (i = 2; i <= NF; i++) { split($i, kv, "="); v[kv[1]] = kv[2] }
  printf "requests %d  failed %d (timeout %d, conn %d, http %d, dropped iterations %d)  error rate %.2f%%  rps %s  p50 %s ms  p95 %s ms  p99 %s ms\n",
    v["requests"], v["failed"], v["timeout"], v["conn"], v["http"], v["dropped"], v["error_rate"] * 100, v["rps"], v["p50_ms"], v["p95_ms"], v["p99_ms"]
  if (v["requests"] + 0 == 0) { print "INCONCLUSIVE: zero requests completed"; exit 3 }
  if (v["error_rate"] + 0 > max + 0) { printf "FAIL: error rate above %s\n", max; exit 1 }
  printf "PASS: error rate within %s\n", max
}'
