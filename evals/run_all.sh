#!/usr/bin/env bash
# Score every eval's reference run: for each evals/<name>/ that has a reference/,
# copy its source app (expect.json "source") to a temp dir, overlay reference/,
# run evals/check.py, and print a summary table. Exit 1 if any eval fails.
#
# Usage: evals/run_all.sh [--no-validate] [--keep] [eval-name...]
#   --no-validate  pass through to check.py (skips k8sa-validate, reported SKIP)
#   --keep         keep the temp dirs and print where they are
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
check_args=()
keep=0
names=()
for arg in "$@"; do
  case "$arg" in
    --no-validate) check_args+=("--no-validate") ;;
    --keep) keep=1 ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) names+=("$arg") ;;
  esac
done
if [ "${#names[@]}" -eq 0 ]; then
  for d in "$here"/*/; do
    [ -d "${d}reference" ] && names+=("$(basename "$d")")
  done
fi
if [ "${#names[@]}" -eq 0 ]; then
  echo "no evals with a reference/ under $here" >&2
  exit 1
fi

work="$(mktemp -d "${TMPDIR:-/tmp}/k8sa-evals.XXXXXX")"
if [ "$keep" -eq 0 ]; then
  trap 'rm -rf "$work"' EXIT
fi

rows=()
failed=0
for name in "${names[@]}"; do
  ev="$here/$name"
  log="$work/$name.log"
  status="FAIL"
  result="-"
  if [ ! -f "$ev/expect.json" ] || [ ! -d "$ev/reference" ]; then
    result="missing expect.json or reference/"
  else
    src="$(python3 "$here/check.py" --print-source "$ev")"
    if [ -z "$src" ] || [ ! -d "$repo/$src" ]; then
      result="source '$src' not found"
    else
      app="$work/$name"
      cp -R "$repo/$src" "$app"
      cp -R "$ev/reference/." "$app/"
      echo "== $name ($src)"
      if python3 "$here/check.py" ${check_args[@]+"${check_args[@]}"} "$ev" "$app" >"$log" 2>&1; then
        status="PASS"
      else
        grep -E '^FAIL ' "$log" || tail -n 20 "$log"
      fi
      result="$(tail -n 1 "$log")"
    fi
  fi
  [ "$status" = "PASS" ] || failed=$((failed + 1))
  rows+=("$(printf '%-4s  %-24s  %s' "$status" "$name" "$result")")
done

echo
printf '%-4s  %-24s  %s\n' "" "EVAL" "RESULT"
for row in "${rows[@]}"; do
  echo "$row"
done
echo
echo "$(( ${#names[@]} - failed ))/${#names[@]} evals passed"
[ "$keep" -eq 1 ] && echo "kept: $work"
[ "$failed" -eq 0 ]
