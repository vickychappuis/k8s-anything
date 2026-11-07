#!/usr/bin/env bash
# Deterministic fingerprint of an app directory, printed as JSON.
# Usage: scripts/detect.sh [app-path]
# Reads files only; never executes project code.
set -euo pipefail

APP="${1:-.}"
[ -d "$APP" ] || { echo "not a directory: $APP" >&2; exit 2; }
cd "$APP"

PRUNE='-name node_modules -o -name .git -o -name .venv -o -name venv -o -name vendor -o -name dist -o -name build -o -name target -o -name .next'

findf() { # findf <maxdepth> <name-pattern>...
  local depth="$1"; shift
  local expr=() first=1
  for n in "$@"; do
    if [ $first -eq 1 ]; then expr+=(-name "$n"); first=0; else expr+=(-o -name "$n"); fi
  done
  # shellcheck disable=SC2086
  find . -maxdepth "$depth" \( $PRUNE \) -prune -o -type f \( "${expr[@]}" \) -print 2>/dev/null | sed 's|^\./||' | sort
}

json_arr() { # newline-separated stdin -> JSON array of strings
  awk 'BEGIN{printf "["} NF{gsub(/\\/,"\\\\");gsub(/"/,"\\\""); printf "%s\"%s\"", (n++?",":""), $0} END{printf "]"}'
}

stacks=""
add_stack() { case " $stacks " in *" $1 "*) ;; *) stacks="$stacks $1";; esac; }
[ -n "$(findf 3 package.json)" ] && add_stack node
[ -n "$(findf 3 pyproject.toml 'requirements*.txt' Pipfile uv.lock poetry.lock)" ] && add_stack python
[ -n "$(findf 3 go.mod)" ] && add_stack go
[ -n "$(findf 3 pom.xml build.gradle build.gradle.kts build.sbt)" ] && add_stack jvm
[ -n "$(findf 3 Gemfile)" ] && add_stack ruby
[ -n "$(findf 3 composer.json)" ] && add_stack php
[ -n "$(findf 3 Cargo.toml)" ] && add_stack rust
[ -n "$(findf 3 '*.csproj' '*.sln')" ] && add_stack dotnet

# Framework hints: grep dependency manifests for well-known names.
frameworks=""
for f in next express fastify @nestjs/core hono nuxt django flask fastapi celery gunicorn uvicorn spring-boot quarkus micronaut rails sidekiq laravel symfony gin echo fiber actix-web axum; do
  if grep -rqsI --include=package.json --include=pyproject.toml --include='requirements*.txt' \
       --include=pom.xml --include='build.gradle*' --include=Gemfile --include=composer.json \
       --include=go.mod --include=Cargo.toml --exclude-dir=node_modules --exclude-dir=.venv \
       -e "[\"/ ]${f}[\"=<>~ @:/]" -e "^${f}[=<>~ ]*" -e "^${f}\$" . 2>/dev/null; then
    frameworks="$frameworks
$f"
  fi
done

dockerfiles=$(findf 4 Dockerfile 'Dockerfile.*' '*.Dockerfile' Containerfile)
compose=$(findf 3 docker-compose.yml docker-compose.yaml compose.yml compose.yaml 'docker-compose.*.yml' 'compose.*.yaml')
procfile=$(findf 2 Procfile)
envfiles=$(findf 3 '.env' '.env.*' '*.env')
helm=$(findf 5 Chart.yaml)
kustomize=$(findf 5 kustomization.yaml kustomization.yml)
k8s_yaml=$( { grep -rlsI --include='*.yaml' --include='*.yml' --exclude-dir=node_modules --exclude-dir=.git -E '^kind: *(Deployment|StatefulSet|Service|Ingress|CronJob)' . 2>/dev/null || true; } | sed 's|^\./||' | sort | head -50)

expose_ports=""
if [ -n "$dockerfiles" ]; then
  expose_ports=$(echo "$dockerfiles" | while read -r d; do grep -hiE '^\s*EXPOSE' "$d" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+' | sed 's|/.*||'; done | sort -u)
fi

compose_ports=""
compose_services=""
if [ -n "$compose" ]; then
  for c in $compose; do
    compose_ports="$compose_ports
$(grep -E '^\s*-\s*"?[0-9.:]*[0-9]+:[0-9]+' "$c" 2>/dev/null | sed -E 's/.*:([0-9]+)(\/[a-z]+)?"?\s*$/\1/' || true)"
    # top-level keys under "services:" at 2-space indent
    compose_services="$compose_services
$(awk '/^services:/{s=1;next} s&&/^[^ #]/{s=0} s&&/^  [A-Za-z0-9_.-]+:/{gsub(/[ :]/,"");print}' "$c")"
  done
fi

env_keys=""
if [ -n "$envfiles" ]; then
  env_keys=$(echo "$envfiles" | while read -r e; do grep -hoE '^[A-Za-z_][A-Za-z0-9_]*=' "$e" 2>/dev/null | tr -d '='; done | sort -u)
fi

procs=""
[ -n "$procfile" ] && procs=$(grep -hoE '^[a-z0-9_-]+:' Procfile | tr -d ':')

cat <<EOF
{
  "path": "$(pwd)",
  "stacks": $(echo "$stacks" | tr ' ' '\n' | json_arr),
  "frameworks": $(echo "$frameworks" | sort -u | json_arr),
  "dockerfiles": $(echo "$dockerfiles" | json_arr),
  "expose_ports": $(echo "$expose_ports" | json_arr),
  "compose_files": $(echo "$compose" | json_arr),
  "compose_services": $(echo "$compose_services" | sort -u | json_arr),
  "compose_container_ports": $(echo "$compose_ports" | sort -u | json_arr),
  "procfile_processes": $(echo "$procs" | json_arr),
  "env_files": $(echo "$envfiles" | json_arr),
  "env_keys": $(echo "$env_keys" | json_arr),
  "existing_helm_charts": $(echo "$helm" | json_arr),
  "existing_kustomizations": $(echo "$kustomize" | json_arr),
  "existing_k8s_manifests": $(echo "$k8s_yaml" | json_arr)
}
EOF
