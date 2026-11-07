#!/usr/bin/env bash
# Local end-to-end smoke test on a throwaway kind cluster.
# Usage: scripts/smoke-kind.sh <app-path> [overlay=dev] [image=<app>:smoke]
# Only ever talks to the kind-k8s-anything context.
set -euo pipefail

APP="$(cd "${1:?usage: smoke-kind.sh <app-path> [overlay] [image]}" && pwd)"
OVERLAY="${2:-dev}"
NAME="$(basename "$APP" | tr '[:upper:]_' '[:lower:]-')"
IMAGE="${3:-$NAME:smoke}"
CLUSTER="k8s-anything"
CTX="kind-$CLUSTER"
KDIR="$APP/deploy/k8s/overlays/$OVERLAY"

for t in docker kind kubectl; do command -v "$t" >/dev/null || { echo "missing: $t" >&2; exit 2; }; done
[ -f "$KDIR/kustomization.yaml" ] || { echo "no overlay at $KDIR" >&2; exit 2; }

kind get clusters 2>/dev/null | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER" --wait 60s
K="kubectl --context $CTX"

echo "== build $IMAGE"
docker build -t "$IMAGE" "$APP"
kind load docker-image "$IMAGE" --name "$CLUSTER"

NS="smoke-$NAME"
$K create namespace "$NS" --dry-run=client -o yaml | $K apply -f -

echo "== apply $KDIR (image override -> $IMAGE)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: $NS
resources:
  - $KDIR
EOF
# Point every image whose name matches the app at the locally built tag.
(cd "$WORK" && kubectl kustomize . ) \
  | sed -E "s#(image: *)([^ ]*/)?$NAME(:[^ ]*)?\$#\1$IMAGE#" \
  | $K apply -f -

echo "== wait for rollouts"
$K -n "$NS" get deploy -o name | while read -r d; do
  $K -n "$NS" rollout status "$d" --timeout=180s
done
$K -n "$NS" get pods -o wide

echo
echo "OK. Inspect:   kubectl --context $CTX -n $NS get all"
echo "Port-forward:  kubectl --context $CTX -n $NS port-forward svc/<service> 8080:<port>"
echo "Clean up:      kubectl --context $CTX delete ns $NS   |   kind delete cluster --name $CLUSTER"
