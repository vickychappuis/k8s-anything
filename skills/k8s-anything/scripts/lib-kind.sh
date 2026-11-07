# shellcheck shell=bash
# Shared by load.sh and chaos.sh (sourced, not run). Resolves the smoke-test target
# on the kind-k8s-anything cluster: namespace, Deployment, its pod selector and the
# Service in front of it. Never reads or changes the current kubectl context.

CTX="kind-k8s-anything"
K=(kubectl --context "$CTX")

die() { echo "$*" >&2; exit 2; }

# Same derivation as smoke-kind.sh: smoke-<short image name>-<overlay>.
smoke_ns() { # <app-path> <overlay>
  local kdir="$1/deploy/k8s/overlays/$2" image repo short
  [ -d "$kdir" ] || die "no overlay at $kdir"
  image="$(kubectl kustomize "$kdir" | awk '/^kind: Deployment/{d=1} d && /^ *image:/{print $2; exit}')"
  [ -n "$image" ] || die "no Deployment image found in $kdir"
  repo="${image%@*}"
  case "${repo##*/}" in *:*) repo="${repo%:*}";; esac
  short="${repo##*/}"
  printf 'smoke-%s' "$(printf '%s-%s' "$short" "$2" | tr -c 'a-z0-9-' '-' | cut -c1-55 | sed 's/-*$//')"
}

# Sets NS, DEPLOY, SELECTOR, SVC, SVC_PORT. Args: NS (may be empty) APP OVERLAY DEPLOY SVC
resolve_target() {
  NS="$1"; DEPLOY="$4"; SVC="$5"
  command -v kubectl >/dev/null || die "missing: kubectl"
  kubectl config get-contexts "$CTX" >/dev/null 2>&1 \
    || die "no kubectl context $CTX — run k8sa-smoke first"
  if [ -z "$NS" ]; then
    [ -n "$2" ] || die "give <app-path> [overlay] or -n <namespace>"
    NS="$(smoke_ns "$(cd "$2" && pwd)" "${3:-dev}")"
  fi
  case "$NS" in smoke-*) ;; *) die "refusing namespace '$NS': only smoke-* namespaces";; esac
  "${K[@]}" get ns "$NS" >/dev/null 2>&1 || die "namespace $NS not found on $CTX — run k8sa-smoke first"
  if [ -z "$DEPLOY" ]; then
    # shellcheck disable=SC2207
    local ds=($("${K[@]}" -n "$NS" get deploy -o name))
    [ "${#ds[@]}" -eq 1 ] || die "found ${#ds[@]} Deployments in $NS; pass --deployment"
    DEPLOY="${ds[0]#*/}"
  fi
  # shellcheck disable=SC2016 # go-template, not shell
  SELECTOR="$("${K[@]}" -n "$NS" get deploy "$DEPLOY" \
    -o go-template='{{range $k, $v := .spec.selector.matchLabels}}{{$k}}={{$v}},{{end}}')"
  SELECTOR="${SELECTOR%,}"
  [ -n "$SELECTOR" ] || die "Deployment $DEPLOY has no matchLabels selector"
  [ -n "$SVC" ] || SVC="$DEPLOY"
  SVC_PORT="$("${K[@]}" -n "$NS" get svc "$SVC" -o jsonpath='{.spec.ports[0].port}' 2>/dev/null)" \
    || die "no Service '$SVC' in $NS; pass --service"
  [ -n "$SVC_PORT" ] || die "Service $SVC has no ports"
}
