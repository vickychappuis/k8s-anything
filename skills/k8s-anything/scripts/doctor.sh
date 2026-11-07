#!/usr/bin/env bash
# Report which underlying tools are available and what's missing.
# Always exits 0: missing optional tools only reduce capability.
set -uo pipefail

# name|stage|level|install hint|docker fallback image
TOOLS="
docker|2,5|recommended|Docker Desktop, OrbStack or colima|
kubectl|3-5|required|brew install kubectl|
kompose|3|optional|brew install kompose|
move2kube|3|optional|brew install konveyor/move2kube/move2kube|
helm|3,5|optional|brew install helm|alpine/helm
pack|2|optional|brew install buildpacks/tap/pack|
hadolint|2|optional|brew install hadolint|hadolint/hadolint
kubeconform|5|recommended|brew install kubeconform|ghcr.io/yannh/kubeconform
kube-linter|5|recommended|brew install kube-linter|stackrox/kube-linter
trivy|2,5|optional|brew install trivy|aquasec/trivy
kind|5|optional|brew install kind|
"

version_of() {
  case "$1" in
    docker)      docker --version ;;
    kubectl)     kubectl version --client ;;
    helm)        helm version --short ;;
    kubeconform) kubeconform -v ;;
    hadolint|trivy) "$1" --version ;;
    *)           "$1" version ;;
  esac 2>/dev/null | head -1
}

daemon=0
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then daemon=1; fi

printf '%-12s %-6s %-22s %s\n' TOOL STAGE STATUS VERSION/HINT
echo "$TOOLS" | while IFS='|' read -r name stage level hint image; do
  [ -z "$name" ] && continue
  if command -v "$name" >/dev/null 2>&1; then
    v="$(version_of "$name" || true)"
    printf '%-12s %-6s %-22s %s\n' "$name" "$stage" ok "${v:-?}"
  elif [ -n "$image" ] && [ $daemon -eq 1 ]; then
    printf '%-12s %-6s %-22s %s\n' "$name" "$stage" "via-docker" "$image  (or: $hint)"
  else
    printf '%-12s %-6s %-22s %s\n' "$name" "$stage" "MISSING($level)" "$hint"
  fi
done

echo
if [ $daemon -eq 1 ]; then
  echo "docker daemon: running"
  if docker init --help >/dev/null 2>&1; then echo "docker init: available"
  else echo "docker init: not available (use assets/dockerfiles templates)"; fi
else
  echo "docker daemon: NOT running (no image builds, no docker fallbacks, no kind)"
fi
command -v python3 >/dev/null 2>&1 || echo "python3: MISSING (needed by k8sa-detect)"

if command -v kubectl >/dev/null 2>&1; then
  ctx="$(kubectl config current-context 2>/dev/null || echo none)"
  echo "kubectl context: $ctx  (k8s-anything never applies to non-kind contexts without approval)"
fi
exit 0
