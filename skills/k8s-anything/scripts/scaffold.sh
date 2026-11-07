#!/usr/bin/env bash
# Copy the hardened Kustomize template into an app and fill placeholders.
# Usage: scaffold.sh <dest-dir> <app-name> <port> [health-path=/healthz] [registry=registry.example.com]
# Example: scaffold.sh ./myapp/deploy/k8s myapp 8000 /healthz ghcr.io/me
set -euo pipefail

usage="usage: scaffold.sh <dest> <app-name> <port> [health-path] [registry]"
DEST="${1:?$usage}"
NAME="${2:?$usage}"
PORT="${3:?$usage}"
HEALTH="${4:-/healthz}"
REGISTRY="${5:-registry.example.com}"
REGISTRY="${REGISTRY%/}"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

die() { echo "scaffold: $*" >&2; exit 2; }

# Service names must be DNS-1035 labels; leave room for "-dev" and "-config" suffixes.
echo "$NAME" | grep -Eq '^[a-z]([a-z0-9-]{0,44}[a-z0-9])?$' \
  || die "app-name must start with a letter, use only a-z 0-9 -, max 46 chars"
echo "$PORT" | grep -Eq '^[0-9]+$' && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] \
  || die "port must be 1-65535"
echo "$HEALTH" | grep -Eq '^/[A-Za-z0-9/._~-]*$' \
  || die "health path must start with / and use only A-Z a-z 0-9 / . _ ~ -"
echo "$REGISTRY" | grep -Eq '^[a-z0-9]([a-z0-9._:/-]*[a-z0-9])?$' \
  || die "registry must look like ghcr.io/org or localhost:5000"
for d in base overlays; do [ -e "$DEST/$d" ] && die "refusing to overwrite existing $DEST/$d"; done

# Render into a temp dir, then move into place: never touch other files in DEST,
# never leave a half-substituted tree behind. Inputs are validated above, so they
# contain no sed metacharacters for the '|' delimiter.
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp -R "$SKILL_DIR/assets/kustomize/base" "$SKILL_DIR/assets/kustomize/overlays" "$WORK/"
find "$WORK" -type f -name '*.yaml' | while IFS= read -r f; do
  sed -e "s|REGISTRY/APP_NAME|$REGISTRY/$NAME|g" -e "s|APP_NAME|$NAME|g" \
      -e "s|APP_PORT|$PORT|g" -e "s|HEALTH_PATH|$HEALTH|g" "$f" > "$f.tmp"
  mv "$f.tmp" "$f"
done
if grep -rqE 'APP_NAME|APP_PORT|HEALTH_PATH|REGISTRY/' "$WORK"; then
  die "internal error: placeholders left after substitution"
fi

mkdir -p "$DEST"
mv "$WORK/base" "$WORK/overlays" "$DEST/"
echo "scaffolded $DEST (app=$NAME port=$PORT health=$HEALTH registry=$REGISTRY)"
