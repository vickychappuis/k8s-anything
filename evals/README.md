# Evals

Each `evals/<name>/` scores a k8s-anything run on one example app by **properties**
(non-root image, secrets not in ConfigMaps, singleton not autoscaled…), not by diffing
against fixed output.

```
evals/<name>/
  expect.json   what a good run must satisfy (schema below)
  reference/    optional: a known-good run, overlaid on the source app by run_all.sh
```

## Running

```bash
# score one run
cp -R examples/flask-redis /tmp/run && (run the skill on /tmp/run)
python3 evals/check.py evals/flask-redis /tmp/run           # table, exit 1 on any FAIL
python3 evals/check.py --json evals/flask-redis /tmp/run    # machine-readable
python3 evals/check.py --no-validate ...                    # skip k8sa-validate (SKIP, not PASS)

# score every reference run (source app + reference/ overlay)
evals/run_all.sh [--no-validate] [--keep] [eval-name...]

# unit tests for the checker
python3 -m unittest discover -s tests -v
```

`check.py` is stdlib-only Python 3.9+. It needs `kubectl`, used offline: `kubectl
kustomize` renders each overlay and `kubectl annotate --local -o json` (with an empty
kubeconfig, so no cluster is ever contacted) converts the YAML to JSON with kubectl's
own decoder. Checks look at structure (probes, selectors, scale targets), not at text.
It also runs `bin/k8sa-validate`; an INCONCLUSIVE validate (exit 3, no validator ran)
is a FAIL.

`expect.json` is validated first: an unknown key or service field (e.g. a typo such as
`secret_keys`), a wrong type, a bad regex or a duplicate service name is a usage error
(exit 2), so a typo can't silently drop checks. Keys starting with `_` are comments.

Output: one `PASS`/`FAIL`/`SKIP` line per check, then
`N/M checks passed, weighted score S%`. Skipped checks don't count in N, M or S.
`--json` prints `{eval, app, passed, failed, skipped, total, score, ok, checks: [{name,
status, category, weight, detail}]}`.

## expect.json schema

All keys are optional except `source`. Paths are relative to the app root.
An overlay that renders no objects still gets every overlay check (and fails them).

| Key | Type | Checks |
|---|---|---|
| `source` | string | Repo-relative path of the example app (`examples/<app>`). Used by `run_all.sh` and `unchanged_files`. |
| `prompt` | string | The prompt given to the agent. Not checked; documents the eval. |
| `overlays` | string[] | Overlays under `deploy/k8s/overlays/` that must build. Default `["dev", "prod"]`. Overlay `dev` and `prod` get the dev/prod-specific checks below. |
| `dockerfiles` | string[] | Dockerfiles to check. Default `["Dockerfile"]`. Each: exists; final stage has a numeric non-root `USER`; no `FROM` image that is `:latest` or untagged (earlier stage names, `scratch`, digests and `${VAR}` images are allowed); a `.dockerignore` next to it, `<Dockerfile>.dockerignore`, or at the app root. |
| `forbidden_cmd_patterns` | regex[] | Must match neither any Dockerfile nor any prod container `command`+`args` (dev servers: `flask\s+run`, `manage\.py\s+runserver`, `next\s+dev`). |
| `build_args_keys` | string[] | Each must be an `ARG` in some Dockerfile (build-time config such as `NEXT_PUBLIC_API_URL`). A trailing `*` is a prefix: `NEXT_PUBLIC_*` needs at least one matching `ARG`. |
| `unchanged_files` | string[] | Byte-identical to `<source>/<file>`: the app's source is not edited. |
| `health_path` | string | Legacy single-app form: when `services` is absent, some container in each overlay has a readiness `httpGet` on this path. With `services`, the default `health_path` for `web` services. |
| `services` | object[] | Per-workload checks in every overlay, see below. |
| `secret_or_dropped_keys` | string[] | Not in any ConfigMap's `data`/`binaryData` (substring of keys or values, so `SECRET_KEY=…` inside an embedded `.env` file counts) and not the name of a plain `env` `value` (every overlay); not inlined in any Secret's `data`/`stringData` in `prod`. |
| `dev_only_images` | string[] | Image basename (`redis` matches `docker.io/library/redis:7`) present in `dev`, absent in every other overlay. |
| `required_emptydir_paths` | string[] or {service: string[]} | Each path is a volumeMount backed by an `emptyDir` (writable dirs under `readOnlyRootFilesystem`, e.g. `/tmp`, `/app/.next/cache`). A list applies to every `web`/`worker`/`singleton` service (or every Deployment/StatefulSet without `services`); a map targets named services. Checked in every overlay. |
| `report_mentions` | string[] | Case-insensitive substrings of `deploy/k8s/K8S_REPORT.md`. |
| `weights` | {category: number} | Overrides the default weight of a check category (see Scoring). |

Always checked: every overlay has a `Namespace`; `prod` has a `PodDisruptionBudget`
and a `NetworkPolicy`; every HPA's scale target exists and has **no** `spec.replicas`
(the HPA owns it); `k8sa-validate` exits 0; the report exists, has the sections
Evidence, Assumptions, Open questions, Checklist, Validation, and cites `file:line`.

### `services`

```json
"services": [
  {"name": "web",     "kind": "web", "health_path": "/healthz", "port": 8000},
  {"name": "worker",  "kind": "worker"},
  {"name": "beat",    "kind": "singleton"},
  {"name": "migrate", "kind": "job", "overlays": ["prod"]},
  {"name": "cleanup", "kind": "cronjob"}
]
```

| Field | Meaning |
|---|---|
| `name` | Matched to a rendered workload by exact `metadata.name`, then a `<prefix>-name` / `name-<suffix>` variant, then label `app.kubernetes.io/component: <name>`. |
| `workload` | Optional: the workload's name, when it differs from `name`. |
| `kind` | `web` (default), `worker`, `singleton`, `job` or `cronjob`. |
| `health_path` | `web`: readiness `httpGet.path` must equal it (otherwise any readiness probe). |
| `port` | `web`: some selecting Service's `targetPort` resolves to this container port (number or port name). |
| `overlays` | Optional: only check in these overlays (e.g. a migration Job only in prod). Also limits its `required_emptydir_paths`. |

| kind | Workload kind | Checks |
|---|---|---|
| `web` | Deployment/StatefulSet | readiness probe (on `health_path`); a Service selects its pods (targeting `port`) |
| `worker` | Deployment/StatefulSet | no Service selects its pods; no network probe (`httpGet`, `tcpSocket`, `grpc`) as readiness/liveness/startup; `exec` probes are fine |
| `singleton` | Deployment/StatefulSet | `replicas` 1 (or unset); Deployment `strategy.type: Recreate`; not the target of an HPA; not selected by any PDB (an empty selector selects all pods) |
| `job` | Job | exists with that kind |
| `cronjob` | CronJob | exists with that kind |

## Scoring

Each check has a category with a weight; the score is passed weight / run weight.

| Category | Weight | Checks |
|---|---|---|
| `build` | 3 | overlays build |
| `security` | 3 | non-root USER, secret keys, dev-only images, emptyDir paths |
| `services` | 3 | per-service checks |
| `validation` | 3 | `k8sa-validate` |
| `container` | 2 | Dockerfile exists, no `:latest`, `.dockerignore`, forbidden commands, build args |
| `source` | 2 | `unchanged_files` |
| `manifests` | 2 | Namespace, legacy readiness, HPA owns replicas, PDB, NetworkPolicy |
| `report` | 1 | `K8S_REPORT.md` |

An eval passes only if no check fails (the weighted score is for comparing runs).

## Adding an eval

1. Put the app under `examples/<app>/`.
2. Write `evals/<app>/expect.json`; prefer properties a correct run must have over
   details of one particular good run.
3. Optionally add a known-good `reference/` (only the files the skill produces) and
   check `evals/run_all.sh <app>` passes.
