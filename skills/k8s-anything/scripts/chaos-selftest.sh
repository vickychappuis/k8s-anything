# shellcheck shell=bash
# Sourced by chaos.sh --self-test (needs CTX, K, die, HERE from lib-kind.sh/chaos.sh).
# Negative control for the chaos harness itself. A real app on single-node kind often
# passes chaos even with no readinessProbe/preStop: the replacement pod starts listening
# within ~1 s, before kube-proxy even routes to it. This fixture takes 8 s to listen,
# so routing to a pod that isn't ready is guaranteed to drop requests:
#   probed   (readinessProbe + preStop) -> chaos must PASS
#   unprobed (neither)                  -> chaos must FAIL
# Anything else means a chaos PASS on this cluster proves nothing about readiness.
# Runs in its own throwaway smoke-* namespace, deleted on exit.

ST_IMAGE="${K8SA_SELFTEST_IMAGE:-busybox:1.37.0}"
ST_NS="smoke-k8sa-selftest-$$"
"${K[@]}" version >/dev/null 2>&1 || die "context $CTX unreachable — run k8sa-smoke first"
# shellcheck disable=SC2329 # invoked by the EXIT trap
st_cleanup() { "${K[@]}" delete ns "$ST_NS" --ignore-not-found --wait=false >/dev/null 2>&1 || true; }
trap st_cleanup EXIT
trap 'exit 3' INT TERM

st_apply() { # <probed: 1|"">
  local extra=""
  if [ -n "$1" ]; then
    extra='          readinessProbe: {httpGet: {path: /, port: 8080}, periodSeconds: 1}
          lifecycle: {preStop: {exec: {command: ["sleep", "3"]}}}'
  fi
  # Client-side apply prunes fields that were in the last applied version, so the
  # second call really removes the probe and preStop.
  st_manifest "$extra" | "${K[@]}" -n "$ST_NS" apply -f - >/dev/null
  "${K[@]}" -n "$ST_NS" rollout status deploy/fixture --timeout=180s >/dev/null \
    || die "self-test fixture did not roll out (image $ST_IMAGE pullable?)"
}
st_manifest() {
  cat <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: fixture, labels: {app.kubernetes.io/name: k8sa-selftest}}
spec:
  replicas: 2
  selector: {matchLabels: {app.kubernetes.io/name: k8sa-selftest}}
  strategy: {rollingUpdate: {maxUnavailable: 0, maxSurge: 1}}
  template:
    metadata: {labels: {app.kubernetes.io/name: k8sa-selftest}}
    spec:
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: 10
      securityContext: {runAsNonRoot: true, runAsUser: 65534, runAsGroup: 65534, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: web
          image: $ST_IMAGE
          command: ["sh", "-c", "sleep 8; mkdir -p /tmp/www && echo ok >/tmp/www/index.html && exec httpd -f -p 8080 -h /tmp/www"]
          ports: [{containerPort: 8080}]
          resources: {requests: {cpu: 10m, memory: 16Mi}, limits: {memory: 32Mi}}
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: ["ALL"]}}
          volumeMounts: [{name: tmp, mountPath: /tmp}]
$1
      volumes: [{name: tmp, emptyDir: {}}]
EOF
}

echo "== chaos self-test in namespace $ST_NS ($ST_IMAGE, 8 s startup)"
"${K[@]}" create ns "$ST_NS" >/dev/null
"${K[@]}" label ns "$ST_NS" pod-security.kubernetes.io/enforce=restricted \
  app.kubernetes.io/managed-by=k8s-anything >/dev/null
"${K[@]}" -n "$ST_NS" create service clusterip fixture --tcp=80:8080 >/dev/null
"${K[@]}" -n "$ST_NS" set selector service fixture app.kubernetes.io/name=k8sa-selftest >/dev/null

st_run() { # <label>; prints chaos output indented, sets ST_RC
  echo "-- $1"
  set +e
  "$HERE/chaos.sh" -n "$ST_NS" --deployment fixture --service fixture \
    --kills 2 --interval 2 --rps 50 --vus 10 2>&1 | grep -E '^(K8SA_RESULT|ZERO-DOWNTIME|INCONCLUSIVE)' | sed 's/^/   /'
  ST_RC=${PIPESTATUS[0]}
  set -e
}
st_apply 1;  st_run "probed fixture (readinessProbe + preStop): expect PASS"; good=$ST_RC
st_apply ""; st_run "unprobed fixture (no readinessProbe, no preStop): expect FAIL"; bad=$ST_RC

if [ "$good" -eq 0 ] && [ "$bad" -eq 1 ]; then
  echo "SELF-TEST OK: chaos tells a readiness-gated Deployment from an ungated one on this cluster."
  exit 0
elif [ "$good" -eq 3 ] || [ "$bad" -eq 3 ] || [ "$good" -eq 2 ] || [ "$bad" -eq 2 ]; then
  echo "SELF-TEST INCONCLUSIVE (probed rc=$good, unprobed rc=$bad)."
  exit 3
fi
echo "SELF-TEST FAILED (probed rc=$good, unprobed rc=$bad): a chaos verdict on this cluster is not trustworthy."
exit 1
