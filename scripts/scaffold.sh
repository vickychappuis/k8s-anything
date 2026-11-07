#!/usr/bin/env bash
# Copy the hardened Kustomize template into an app and fill placeholders.
# Usage: scripts/scaffold.sh <dest-dir> <app-name> <port> [health-path=/healthz] [registry=registry.example.com]
# Example: scripts/scaffold.sh ./myapp/deploy/k8s myapp 8000 /healthz ghcr.io/me
set -euo pipefail

DEST="${1:?usage: scaffold.sh <dest> <app-name> <port> [health-path] [registry]}"
NAME="${2:?app-name required}"
PORT="${3:?port required}"
HEALTH="${4:-/healthz}"
REGISTRY="${5:-registry.example.com}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

case "$NAME" in *[!a-z0-9-]*|-*|*-) echo "app-name must be a DNS-1123 label (a-z, 0-9, -)" >&2; exit 2;; esac
case "$PORT" in *[!0-9]*|'') echo "port must be numeric" >&2; exit 2;; esac
[ -e "$DEST/base" ] && { echo "refusing to overwrite existing $DEST/base" >&2; exit 2; }

mkdir -p "$DEST"
cp -R "$ROOT/templates/kustomize/base" "$ROOT/templates/kustomize/overlays" "$DEST/"
find "$DEST" -type f -name '*.yaml' -print0 | while IFS= read -r -d '' f; do
  sed -i.bak -e "s#REGISTRY/APP_NAME#$REGISTRY/$NAME#g" -e "s#APP_NAME#$NAME#g" \
             -e "s#APP_PORT#$PORT#g" -e "s#HEALTH_PATH#$HEALTH#g" "$f"
  rm -f "$f.bak"
done
echo "scaffolded $DEST (app=$NAME port=$PORT health=$HEALTH registry=$REGISTRY)"
