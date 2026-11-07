#!/usr/bin/env bash
# Local end-to-end smoke test on a throwaway kind cluster.
# Usage: smoke-kind.sh <app-path> [overlay=dev]
# Builds <app-path>/Dockerfile, loads it into kind, applies the overlay with every
# image whose name matches the app's image swapped for the local build, and waits
# for rollouts. Only ever talks to the kind-k8s-anything context, and restores your
# previous kubectl context afterwards.
set -euo pipefail

APP="$(cd "${1:?usage: smoke-kind.sh <app-path> [overlay]}" && pwd)"
OVERLAY="${2:-dev}"
CLUSTER="k8s-anything"
GATEWAY_API_VERSION="${GATEWAY_API_VERSION:-v1.7.0}"
CTX="kind-$CLUSTER"
KROOT="$APP/deploy/k8s"
KDIR="$KROOT/overlays/$OVERLAY"

for t in docker kind kubectl; do command -v "$t" >/dev/null || { echo "missing: $t" >&2; exit 2; }; done
[ -d "$KDIR" ] || { echo "no overlay at $KDIR" >&2; exit 2; }
[ -f "$APP/Dockerfile" ] || { echo "no Dockerfile in $APP" >&2; exit 2; }

# The app image is the first container image of the first Deployment in the overlay.
RENDERED="$(kubectl kustomize "$KDIR")"
APP_IMAGE="$(printf '%s\n' "$RENDERED" | awk '/^kind: Deployment/{d=1} d && /^ *image:/{print $2; exit}')"
[ -n "$APP_IMAGE" ] || { echo "no Deployment image found in $KDIR" >&2; exit 2; }
REPO="${APP_IMAGE%@*}"                      # drop digest
case "${REPO##*/}" in *:*) REPO="${REPO%:*}";; esac   # drop tag (not a registry port)
SHORT="${REPO##*/}"
LOCAL="$SHORT:smoke"
NS="smoke-$(printf '%s-%s' "$SHORT" "$OVERLAY" | tr -c 'a-z0-9-' '-' | cut -c1-55 | sed 's/-*$//')"

PREV_CTX="$(kubectl config current-context 2>/dev/null || true)"
restore_ctx() {
  if [ -n "$PREV_CTX" ]; then kubectl config use-context "$PREV_CTX" >/dev/null 2>&1 || true
  else kubectl config unset current-context >/dev/null 2>&1 || true; fi
}
trap restore_ctx EXIT

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER" --wait 120s
  restore_ctx
fi
K=(kubectl --context "$CTX")

echo "== build $LOCAL (app image in manifests: $APP_IMAGE)"
docker build -t "$LOCAL" "$APP"
kind load docker-image "$LOCAL" --name "$CLUSTER"

# Wrapper kustomization must live under the app tree: kustomize rejects absolute
# resource paths.
WORK="$(mktemp -d "$KROOT/.smoke.XXXXXX")"
trap 'rm -rf "$WORK"; restore_ctx' EXIT
cat > "$WORK/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: $NS
resources:
  - ../overlays/$OVERLAY
images:
  - name: $REPO
    newName: $SHORT
    newTag: smoke
EOF
# kind ships no Gateway API CRDs; install the pinned standard channel if needed.
if printf '%s\n' "$RENDERED" | grep -q '^apiVersion: gateway.networking.k8s.io/'; then
  echo "== install Gateway API CRDs $GATEWAY_API_VERSION"
  "${K[@]}" apply --server-side -f \
    "https://github.com/kubernetes-sigs/gateway-api/releases/download/$GATEWAY_API_VERSION/standard-install.yaml" >/dev/null
fi
# The overlay's own Namespace object is renamed by the namespace transformer.
echo "== apply overlay '$OVERLAY' into namespace $NS"
"${K[@]}" create namespace "$NS" --dry-run=client -o yaml | "${K[@]}" apply -f -
kubectl kustomize "$WORK" | "${K[@]}" apply -f -

# Secrets the overlay references but doesn't define (prod creates them out-of-band):
# create placeholders so the rollout can be exercised. Never real values.
kubectl kustomize "$WORK" | python3 -I -c '
import re, sys
docs = re.split(r"^---\s*$", sys.stdin.read(), flags=re.M)
defined = {re.search(r"^  name:\s*(\S+)", d, re.M).group(1)
           for d in docs if re.search(r"^kind:\s*Secret\s*$", d, re.M)}
refs = {}
for d in docs:
    for m in re.finditer(r"secretRef:\s*\n\s*name:\s*(\S+)", d):
        refs.setdefault(m.group(1), set())
    for m in re.finditer(r"secretKeyRef:\s*\n((?:\s+\w+:.*\n){1,3})", d):
        blk = m.group(1)
        n = re.search(r"name:\s*(\S+)", blk); k = re.search(r"key:\s*(\S+)", blk)
        if n:
            refs.setdefault(n.group(1), set()).update([k.group(1)] if k else [])
for name, keys in sorted(refs.items()):
    if name not in defined:
        print(name, " ".join(sorted(keys)))
' | while read -r sname skeys; do
  echo "== placeholder Secret $sname (keys: ${skeys:-none}) — smoke test only"
  set -- ; for k in $skeys; do set -- "$@" "--from-literal=$k=smoke-placeholder"; done
  "${K[@]}" -n "$NS" create secret generic "$sname" "$@" --dry-run=client -o yaml | "${K[@]}" apply -f -
done

echo "== wait for rollouts"
for kind in deploy statefulset; do
  for r in $("${K[@]}" -n "$NS" get "$kind" -o name); do
    "${K[@]}" -n "$NS" rollout status "$r" --timeout=180s
  done
done
"${K[@]}" -n "$NS" get pods -o wide

echo
echo "OK. Inspect:   kubectl --context $CTX -n $NS get all"
echo "Port-forward:  kubectl --context $CTX -n $NS port-forward svc/<service> 8080:80"
echo "Clean up:      kubectl --context $CTX delete ns $NS   |   kind delete cluster --name $CLUSTER"
