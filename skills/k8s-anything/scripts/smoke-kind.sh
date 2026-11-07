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
NS="smoke-$(printf '%s' "$SHORT" | tr -c 'a-z0-9-' '-' | cut -c1-50 | sed 's/-*$//')"

PREV_CTX="$(kubectl config current-context 2>/dev/null || true)"
restore_ctx() { [ -n "$PREV_CTX" ] && kubectl config use-context "$PREV_CTX" >/dev/null 2>&1 || true; }
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
# The overlay's own Namespace object is renamed by the namespace transformer.
echo "== apply overlay '$OVERLAY' into namespace $NS"
"${K[@]}" create namespace "$NS" --dry-run=client -o yaml | "${K[@]}" apply -f -
kubectl kustomize "$WORK" | "${K[@]}" apply -f -

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
