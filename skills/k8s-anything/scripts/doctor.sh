#!/usr/bin/env bash
# Report which underlying tools are available and what's missing.
# Exit code is always 0: missing optional tools only reduce capability.
set -euo pipefail

# name|stage|install hint|required?
TOOLS="
docker|2,5|Docker Desktop, OrbStack or colima|recommended
kubectl|3-5|brew install kubectl|required
kompose|3|brew install kompose|optional
move2kube|3|brew install konveyor/move2kube/move2kube|optional
helm|3|brew install helm|optional
pack|2|brew install buildpacks/tap/pack|optional
hadolint|2|brew install hadolint|optional
kubeconform|5|brew install kubeconform|recommended
kube-linter|5|brew install kube-linter|recommended
trivy|2,5|brew install trivy|optional
kind|5|brew install kind|optional
"

printf '%-12s %-6s %-12s %s\n' TOOL STAGE STATUS VERSION/HINT
echo "$TOOLS" | while IFS='|' read -r name stage hint level; do
  [ -z "$name" ] && continue
  if command -v "$name" >/dev/null 2>&1; then
    case "$name" in
      docker)      v=$(docker --version 2>/dev/null | head -1) ;;
      kubectl)     v=$(kubectl version --client 2>/dev/null | head -1) ;;
      helm)        v=$(helm version --short 2>/dev/null) ;;
      kube-linter) v=$(kube-linter version 2>/dev/null) ;;
      kubeconform) v=$(kubeconform -v 2>/dev/null) ;;
      *)           v=$("$name" version 2>/dev/null | head -1 || true) ;;
    esac
    printf '%-12s %-6s %-12s %s\n' "$name" "$stage" ok "${v:-?}"
  else
    printf '%-12s %-6s %-12s %s\n' "$name" "$stage" "MISSING($level)" "$hint"
  fi
done

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo; echo "docker daemon: running"
  docker init --help >/dev/null 2>&1 && echo "docker init: available" || echo "docker init: not available (use stack templates)"
else
  echo; echo "docker daemon: NOT running (image builds and kind smoke test unavailable)"
fi

if command -v kubectl >/dev/null 2>&1; then
  ctx=$(kubectl config current-context 2>/dev/null || echo none)
  echo "kubectl context: $ctx  (k8s-anything never applies to non-kind contexts without approval)"
fi
