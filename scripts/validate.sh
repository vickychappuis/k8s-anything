#!/usr/bin/env bash
# Static validation of Kubernetes manifests.
# Usage: scripts/validate.sh <dir> [k8s-version]
#   <dir> may be: a Kustomize root with overlays/ (validates each overlay),
#   a single kustomization dir, or a plain directory of YAML files.
# Missing tools are skipped with a warning. Exit 1 if any check that ran failed.
set -uo pipefail

DIR="${1:?usage: validate.sh <dir> [k8s-version]}"
K8S_VERSION="${2:-1.31.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LINT_CFG="$ROOT/policies/kube-linter.yaml"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail=0

have() { command -v "$1" >/dev/null 2>&1; }
warn() { printf '  [skip] %s\n' "$*"; }
hdr()  { printf '\n== %s ==\n' "$*"; }

render() { # render <kustomization-dir> <out-file>
  if have kubectl; then kubectl kustomize "$1" > "$2"
  elif have kustomize; then kustomize build "$1" > "$2"
  else echo "need kubectl or kustomize to render $1" >&2; return 1; fi
}

targets=()
if [ -d "$DIR/overlays" ]; then
  for o in "$DIR"/overlays/*/; do [ -f "$o/kustomization.yaml" ] && targets+=("${o%/}"); done
elif [ -f "$DIR/kustomization.yaml" ]; then
  targets+=("$DIR")
fi

check_file() { # check_file <label> <rendered-yaml-or-dir>
  local label="$1" input="$2"
  hdr "$label"
  if have kubeconform; then
    echo "-- kubeconform (k8s $K8S_VERSION)"
    kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version "$K8S_VERSION" "$input" || fail=1
  else warn "kubeconform not installed"; fi

  if have kube-linter; then
    echo "-- kube-linter"
    kube-linter lint --config "$LINT_CFG" "$input" || fail=1
  else warn "kube-linter not installed"; fi

  if have trivy; then
    echo "-- trivy config"
    trivy config --quiet --exit-code 1 --severity HIGH,CRITICAL "$input" || fail=1
  else warn "trivy not installed"; fi
}

if [ ${#targets[@]} -gt 0 ]; then
  for t in "${targets[@]}"; do
    name="$(basename "$t")"
    out="$TMP/$name/all.yaml"; mkdir -p "$TMP/$name"
    if render "$t" "$out"; then
      echo "rendered $t -> $(grep -c '^kind:' "$out") resources"
      check_file "overlay: $name" "$out"
    else
      hdr "overlay: $name"; echo "  [FAIL] kustomize build failed"; fail=1
    fi
  done
else
  check_file "dir: $DIR" "$DIR"
fi

hdr "result"
if [ $fail -eq 0 ]; then echo "PASS (checks that ran are clean)"; else echo "FAIL"; fi
exit $fail
