#!/usr/bin/env bash
# Local end-to-end smoke test on a throwaway kind cluster.
# Usage: smoke-kind.sh <app-path> [overlay=dev]
# Builds <app-path>/Dockerfile, loads it into kind, applies the overlay with every
# image whose name matches the app's image swapped for the local build, and waits
# for rollouts and Jobs. Only ever talks to the kind-k8s-anything context, and
# restores your previous kubectl context afterwards.
# Multi-image apps: <app>/deploy/k8s/images.txt (format: references/5-validate.md).
# Without it, only the first Deployment's image is built, from <app>/Dockerfile.
set -euo pipefail
set -f   # no globbing: build args from images.txt are split on whitespace on purpose

APP="$(cd "${1:?usage: smoke-kind.sh <app-path> [overlay]}" && pwd)"
OVERLAY="${2:-dev}"
CLUSTER="k8s-anything"
GATEWAY_API_VERSION="${GATEWAY_API_VERSION:-v1.7.0}"
TIMEOUT="${K8SA_SMOKE_TIMEOUT:-300}"   # seconds, per rollout / Job
case "$TIMEOUT" in ''|*[!0-9]*) echo "K8SA_SMOKE_TIMEOUT must be seconds, got '$TIMEOUT'" >&2; exit 2;; esac
CTX="kind-$CLUSTER"
KROOT="$APP/deploy/k8s"
KDIR="$KROOT/overlays/$OVERLAY"

for t in docker kind kubectl; do command -v "$t" >/dev/null || { echo "missing: $t" >&2; exit 2; }; done
[ -d "$KDIR" ] || { echo "no overlay at $KDIR" >&2; exit 2; }
[ -f "$APP/Dockerfile" ] || { echo "no Dockerfile in $APP" >&2; exit 2; }

RENDERED="$(kubectl kustomize "$KDIR")"
repo_of() { # image ref -> repository (drop digest, then tag but not a registry port)
  local r="${1%@*}"
  case "${r##*/}" in *:*) r="${r%:*}";; esac
  printf '%s' "$r"
}
# BUILDS: one "<repo in rendered overlay>|<short name>|<docker build args>" per line.
IMAGES_FILE="$KROOT/images.txt"
RIMAGES="$(printf '%s\n' "$RENDERED" | awk '/^[ -]*image:/{gsub(/["\047]/, "", $NF); print $NF}' | sort -u)"
BUILDS=""
if [ -f "$IMAGES_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"; line="${line%%#*}"          # CRLF files, comments
    read -r name args <<<"$line" || true
    [ -n "$name" ] || continue
    case "$args" in *'|'*) echo "images.txt: '|' not allowed in build args" >&2; exit 2;; esac
    repo=""   # exact match on the full repository or its last path segment, never a prefix
    for img in $RIMAGES; do
      r="$(repo_of "$img")"
      if [ "$r" = "$name" ] || [ "${r##*/}" = "${name##*/}" ]; then repo="$r"; break; fi
    done
    [ -n "$repo" ] || { echo "images.txt: '$name' is not used by overlay $OVERLAY" >&2; exit 2; }
    BUILDS="$BUILDS$repo|${name##*/}|$args
"
  done < "$IMAGES_FILE"
  [ -n "$BUILDS" ] || { echo "images.txt lists no images" >&2; exit 2; }
else
  # The app image is the first container image of the first Deployment in the overlay.
  APP_IMAGE="$(printf '%s\n' "$RENDERED" | awk '/^kind: Deployment/{d=1} d && /^[ -]*image:/{print $NF; exit}')"
  [ -n "$APP_IMAGE" ] || { echo "no Deployment image found in $KDIR" >&2; exit 2; }
  REPO="$(repo_of "$APP_IMAGE")"
  BUILDS="$REPO|${REPO##*/}|
"
fi
SHORT="$(printf '%s' "$BUILDS" | head -n 1 | cut -d'|' -f2)"
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

IMAGES_KUST=""
while IFS='|' read -r repo short args; do
  [ -n "$repo" ] || continue
  echo "== build $short:smoke (image in manifests: $repo) ${args:+[$args]}"
  # shellcheck disable=SC2086  # args are docker flags from images.txt, split on purpose
  (cd "$APP" && docker build -t "$short:smoke" $args .)
  kind load docker-image "$short:smoke" --name "$CLUSTER"
  IMAGES_KUST="$IMAGES_KUST  - name: $repo
    newName: $short
    newTag: smoke
"
done <<EOF
$BUILDS
EOF

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
$IMAGES_KUST
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
# Key names for envFrom-only Secrets come from secret.example.yaml files, if any.
kubectl kustomize "$WORK" | python3 -I -c '
import glob, os, re, sys
docs = re.split(r"^---\s*$", sys.stdin.read(), flags=re.M)
examples = {}
for f in glob.glob(os.path.join(sys.argv[1], "**", "secret*.example.yaml"), recursive=True):
    for d in re.split(r"^---\s*$", open(f, encoding="utf-8", errors="replace").read(), flags=re.M):
        n = re.search(r"^  name:\s*[\x27\x22]?([\w.-]+)", d, re.M)
        body = re.search(r"^(?:stringData|data):\s*\n((?:(?:  .*)?\n)*)", d + "\n", re.M)
        if n and body:
            examples.setdefault(n.group(1), set()).update(
                re.findall(r"^  ([A-Za-z_][\w.-]*):", body.group(1), re.M))
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
        print(name, " ".join(sorted(keys | examples.get(name, set()))))
' "$APP/deploy" | while read -r sname skeys; do
  echo "$sname" >> "$WORK/placeholders"
  echo "== placeholder Secret $sname (keys: ${skeys:-none}) — smoke test only"
  set -- ; for k in $skeys; do
    # URL-shaped keys get a parseable URL to an unresolvable host, so config parsers
    # don't crash at import; anything that actually connects still fails.
    h="placeholder:placeholder@smoke-placeholder.invalid"
    case "$k" in
      *DATABASE_URL|*POSTGRES*_URL|*PG*_URL) v="postgres://$h:5432/placeholder" ;;
      *MYSQL*_URL) v="mysql://$h:3306/placeholder" ;;
      *REDIS*_URL|*BROKER*_URL|*CACHE*_URL) v="redis://$h:6379/0" ;;
      *AMQP*_URL|*RABBIT*_URL) v="amqp://$h:5672/" ;;
      *MONGO*_URL|*MONGO*_URI) v="mongodb://$h:27017/placeholder" ;;
      *URL|*URI) v="https://$h/" ;;
      *) v="smoke-placeholder" ;;
    esac
    set -- "$@" "--from-literal=$k=$v"
  done
  "${K[@]}" -n "$NS" create secret generic "$sname" "$@" --dry-run=client -o yaml | "${K[@]}" apply -f -
done

# Jobs first: a failing migration fails the smoke test as soon as the Job gives up,
# instead of after a rollout that waits for its schema times out.
JOB_FAILED=0
job_diag() { # Job conditions, then pod logs (a failed OnFailure pod may be gone)
  "${K[@]}" -n "$NS" get "$1" -o jsonpath='{range .status.conditions[*]}{.type}: {.reason} {.message}{"\n"}{end}' 2>&1 | sed 's/^/   | /' || true
  "${K[@]}" -n "$NS" logs "$1" --all-containers --tail=30 --request-timeout=10s 2>&1 | sed 's/^/   | /' || true
}
wait_job() { # $1 = job/<name>
  local end=$(( $(date +%s) + TIMEOUT )) st
  while :; do
    st="$("${K[@]}" -n "$NS" get "$1" --ignore-not-found \
      -o jsonpath='{.metadata.name}{range .status.conditions[?(@.status=="True")]}{" "}{.type}{end}')"
    case " $st " in
      "  ") echo "   $1 is gone (ttlSecondsAfterFinished)"; return 0;;
      *" Complete "*) echo "   $1 complete"; return 0;;
      *" Failed "*|*" FailureTarget "*)
        job_diag "$1"
        # Prod overlays have no database: a Job fed placeholder Secrets can't succeed.
        if [ -f "$WORK/placeholders" ] && "${K[@]}" -n "$NS" get "$1" -o yaml \
            | grep -qwFf "$WORK/placeholders"; then
          echo "   WARN: $1 failed; it uses placeholder Secrets, so that's expected here"
          return 0
        fi
        echo "FAIL: $1 failed" >&2; JOB_FAILED=1; return 0;;
    esac
    if [ "$(date +%s)" -ge "$end" ]; then
      job_diag "$1"
      echo "FAIL: $1 not complete after ${TIMEOUT}s" >&2; JOB_FAILED=1; return 0
    fi
    sleep 5
  done
}
echo "== wait for Jobs"
for r in $("${K[@]}" -n "$NS" get job -o name); do wait_job "$r"; done
[ "$JOB_FAILED" = 0 ] || exit 1

echo "== wait for rollouts"
for kind in deploy statefulset; do
  for r in $("${K[@]}" -n "$NS" get "$kind" -o name); do
    "${K[@]}" -n "$NS" rollout status "$r" --timeout="${TIMEOUT}s"
  done
done
"${K[@]}" -n "$NS" get pods -o wide

echo
echo "OK. Inspect:   kubectl --context $CTX -n $NS get all"
echo "Port-forward:  kubectl --context $CTX -n $NS port-forward svc/<service> 8080:80"
echo "Clean up:      kubectl --context $CTX delete ns $NS   |   kind delete cluster --name $CLUSTER"
