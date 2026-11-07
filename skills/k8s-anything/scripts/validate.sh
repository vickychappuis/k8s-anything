#!/usr/bin/env bash
# Static validation of Kubernetes manifests.
# Usage: validate.sh <dir> [k8s-version]
#   <dir>: a Helm chart (Chart.yaml; rendered once per values-*.yaml), a directory
#   of charts (e.g. deploy/helm), a Kustomize root with overlays/ (validates each
#   overlay), a single kustomization dir, or a plain directory of YAML files.
# Each validator runs from the local binary, else from its Docker image (if the
# Docker daemon is up), else is skipped.
# Exit: 0 PASS, 1 FAIL, 2 usage error, 3 INCONCLUSIVE (no validator ran).
set -uo pipefail

DIR="${1:?usage: validate.sh <dir> [k8s-version]}"
K8S_VERSION="${2:-1.31.0}"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LINT_CFG="$SKILL_DIR/assets/kube-linter.yaml"

KUBECONFORM_IMG="ghcr.io/yannh/kubeconform:v0.6.7"
KUBELINTER_IMG="stackrox/kube-linter:v0.8.3"
TRIVY_IMG="aquasec/trivy:0.58.1"
HELM_IMG="alpine/helm:3.16.4"

[ -d "$DIR" ] || { echo "not a directory: $DIR" >&2; exit 2; }
DIR="$(cd "$DIR" && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail=0
ran=0

have() { command -v "$1" >/dev/null 2>&1; }
docker_ok() { have docker && docker info >/dev/null 2>&1; }
hdr() { printf '\n== %s ==\n' "$*"; }
skip() { printf '  [skip] %s\n' "$*"; }

kfile() { # kfile <dir> -> prints the kustomization file name if present
  for f in kustomization.yaml kustomization.yml Kustomization; do
    [ -f "$1/$f" ] && { echo "$f"; return 0; }
  done
  return 1
}

render() { # render <kustomization-dir> <out-file>
  if have kubectl; then kubectl kustomize "$1" > "$2"
  elif have kustomize; then kustomize build "$1" > "$2"
  else echo "  need kubectl or kustomize to render $1" >&2; return 1; fi
}

# helm_run <chart-dir> <args...> — args may reference the chart dir as @CHART@.
# Local helm, else the pinned alpine/helm image with the chart mounted read-only.
helm_run() {
  local chart="$1" args=() a; shift
  if have helm; then
    for a in "$@"; do args+=("${a//@CHART@/$chart}"); done
    helm "${args[@]}"
  elif docker_ok; then
    for a in "$@"; do args+=("${a//@CHART@//chart}"); done
    docker run --rm -v "$chart:/chart:ro" "$HELM_IMG" "${args[@]}"
  else
    return 127
  fi
}

# run_tool <name> <image> <args...>  — args may reference the input as @IN@ and the
# lint config as @CFG@; paths are rewritten for the container.
run_tool() {
  local name="$1" image="$2"; shift 2
  local in_host="$INPUT" args=() a
  if have "$name"; then
    for a in "$@"; do a="${a//@IN@/$in_host}"; args+=("${a//@CFG@/$LINT_CFG}"); done
    "$name" "${args[@]}"
  elif docker_ok; then
    echo "  (via docker: $image)"
    local in_dir in_base
    if [ -d "$in_host" ]; then in_dir="$in_host"; in_base=""; else in_dir="$(dirname "$in_host")"; in_base="/$(basename "$in_host")"; fi
    for a in "$@"; do a="${a//@IN@//in$in_base}"; args+=("${a//@CFG@//cfg/kube-linter.yaml}"); done
    docker run --rm -v "$in_dir:/in:ro" -v "$(dirname "$LINT_CFG"):/cfg:ro" "$image" "${args[@]}"
  else
    return 127
  fi
}

check() { # check <label> <rendered-file-or-yaml-dir>
  local label="$1" rc
  INPUT="$2"
  hdr "$label"

  echo "-- kubeconform (k8s $K8S_VERSION)"
  run_tool kubeconform "$KUBECONFORM_IMG" -strict -summary -ignore-missing-schemas \
    -kubernetes-version "$K8S_VERSION" @IN@; rc=$?
  case $rc in 0) ran=$((ran+1));; 127) skip "kubeconform: no binary and no docker";; *) ran=$((ran+1)); fail=1;; esac

  echo "-- kube-linter"
  run_tool kube-linter "$KUBELINTER_IMG" lint --config @CFG@ @IN@; rc=$?
  case $rc in 0) ran=$((ran+1));; 127) skip "kube-linter: no binary and no docker";; *) ran=$((ran+1)); fail=1;; esac

  if have trivy || [ "${K8SA_TRIVY_DOCKER:-0}" = 1 ]; then
    echo "-- trivy config"
    run_tool trivy "$TRIVY_IMG" config --quiet --exit-code 1 --severity HIGH,CRITICAL @IN@; rc=$?
    case $rc in 0) ran=$((ran+1));; 127) skip "trivy: no binary and no docker";; *) ran=$((ran+1)); fail=1;; esac
  else
    skip "trivy not installed (set K8SA_TRIVY_DOCKER=1 to run it via docker)"
  fi
}

validate_chart() { # validate_chart <chart-dir>: render once per values-*.yaml, check each
  local c="$1" cname v env label out rc n vfiles vargs
  cname="$(awk '$1 == "name:" {gsub(/["\047]/, "", $2); print $2; exit}' "$c/Chart.yaml")"
  [ -n "$cname" ] || cname="$(basename "$c")"
  # The chart defaults alone ("-": what a bare `helm install` gets), then each
  # values-<env>.yaml layered on values.yaml, like an overlay on a base.
  vfiles=("-")
  for v in "$c"/values-*.yaml "$c"/values-*.yml; do [ -f "$v" ] && vfiles+=("$(basename "$v")"); done
  for v in "${vfiles[@]}"; do
    if [ "$v" = "-" ]; then env="defaults"; label="helm $cname (values.yaml)"; vargs=()
    else env="${v#values-}"; env="${env%.y*ml}"; label="helm $cname ($v)"; vargs=(-f "@CHART@/$v"); fi
    mkdir -p "$TMP/$cname-$env"; out="$TMP/$cname-$env/rendered.yaml"
    # ${vargs[@]+...}: bash 3.2 treats an empty array as unset under `set -u`.
    helm_run "$c" template "$cname" @CHART@ ${vargs[@]+"${vargs[@]}"} --namespace "$cname" \
      --kube-version "$K8S_VERSION" > "$out" 2> "$TMP/helm.err"; rc=$?
    n="$(grep -c '^kind:' "$out")"
    if [ $rc -eq 0 ] && [ "$n" -eq 0 ]; then
      echo "  rendered no resources" > "$TMP/helm.err"; rc=1
    fi
    case $rc in
      0)
        echo "rendered $label -> $n resources"
        check "$label" "$out"
        echo "-- helm lint --strict"
        helm_run "$c" lint @CHART@ ${vargs[@]+"${vargs[@]}"} --strict --quiet \
          --kube-version "$K8S_VERSION"; rc=$?
        case $rc in 0) ran=$((ran+1));; 127) skip "helm lint: no binary and no docker";; *) ran=$((ran+1)); fail=1;; esac
        ;;
      127) hdr "$label"; skip "helm: no binary and no docker, chart not rendered" ;;
      *) hdr "$label"; sed 's/^/  /' "$TMP/helm.err"; echo "  [FAIL] helm template failed"; fail=1 ;;
    esac
  done
}

charts=()
if [ -f "$DIR/Chart.yaml" ]; then
  charts+=("$DIR")
else
  for c in "$DIR"/*/; do [ -f "$c/Chart.yaml" ] && charts+=("${c%/}"); done
fi
targets=()
if [ ${#charts[@]} -eq 0 ]; then
  if [ -d "$DIR/overlays" ]; then
    for o in "$DIR"/overlays/*/; do kfile "$o" >/dev/null && targets+=("${o%/}"); done
  fi
  if [ ${#targets[@]} -eq 0 ] && kfile "$DIR" >/dev/null; then
    targets+=("$DIR")
  fi
fi

if [ ${#charts[@]} -gt 0 ]; then
  if ! have helm && docker_ok; then echo "helm: not installed, using $HELM_IMG via docker"; fi
  for c in "${charts[@]}"; do validate_chart "$c"; done
elif [ ${#targets[@]} -gt 0 ]; then
  for t in "${targets[@]}"; do
    name="$(basename "$t")"
    mkdir -p "$TMP/$name"; out="$TMP/$name/rendered.yaml"
    if render "$t" "$out"; then
      echo "rendered ${t#"$DIR"/} -> $(grep -c '^kind:' "$out") resources"
      check "$name" "$out"
    else
      hdr "$name"; echo "  [FAIL] kustomize build failed"; fail=1
    fi
  done
else
  n=$(find "$DIR" -type f \( -name '*.yaml' -o -name '*.yml' \) | wc -l | tr -d ' ')
  [ "$n" -gt 0 ] || { echo "no YAML files under $DIR" >&2; exit 2; }
  check "dir: $DIR ($n files)" "$DIR"
fi

hdr "result"
if [ $fail -ne 0 ]; then echo "FAIL"; exit 1
elif [ $ran -eq 0 ]; then echo "INCONCLUSIVE: no validator ran (install kubeconform/kube-linter/helm or start Docker)"; exit 3
else echo "PASS ($ran checks ran)"; exit 0; fi
