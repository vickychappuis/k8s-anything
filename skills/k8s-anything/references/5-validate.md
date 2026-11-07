# Stage 5 — Validate

## Static

```bash
k8sa-validate <app>/deploy/k8s
k8sa-validate <app>/deploy/helm   # charts: helm template per values-*.yaml (references/helm.md)
```

Per overlay: `kubectl kustomize` → kubeconform (strict, k8s 1.31 by default; pass a
version as the 2nd argument) → kube-linter (`assets/kube-linter.yaml`) → trivy config
(if installed, or `K8SA_TRIVY_DOCKER=1`). Each validator runs from its local binary,
else from a pinned Docker image if Docker is running.

| Exit | Meaning | What you report |
|---|---|---|
| 0 | PASS — every check that ran is clean | paste the summary |
| 1 | FAIL | fix and re-run |
| 2 | usage error (bad path, no YAML) | fix the call |
| 3 | INCONCLUSIVE — no validator could run | say so plainly; **never call it a pass** |

kubeconform skips resources without a known schema (CRDs such as `HTTPRoute`). PASS
still holds, but list the skipped kinds in the report.

For a lint finding you intentionally keep, annotate the object with
`ignore-check.kube-linter.io/<check>: "<reason>"` and list it in the report.

Also validate files not in any kustomization (e.g. an unused `httproute.yaml`) only
if you changed them.

## Dynamic (optional, local only, ask first)

```bash
k8sa-smoke <app-path> [overlay]   # default: dev
```

Builds the app image, creates/reuses a `kind` cluster named `k8s-anything`, loads the
image, swaps it into the overlay's manifests, installs Gateway API CRDs if the overlay
uses them, creates clearly-labelled placeholder Secrets for any Secret the overlay
references but doesn't define (prod creates those out-of-band), applies everything
into a `smoke-<app>-<overlay>` namespace, waits for Deployments/StatefulSets to roll
out and for Jobs to complete. Your previous kubectl context is restored. Requires
Docker, kind, python3.

Placeholder Secrets get the keys the manifests reference, plus the keys of any
`secret*.example.yaml` under `deploy/` with the same name (so `envFrom` works). Keys
ending in `URL`/`URI` get a parseable URL to an unresolvable host (scheme guessed from
the name: postgres, mysql, redis, amqp, mongodb, else https), so config parsing
succeeds and anything that connects fails. Write `secret.example.yaml` for every
out-of-band Secret.

Jobs are waited for first and fail the test as soon as they fail (logs are printed).
Jobs that read a placeholder Secret are not waited for (they can't reach a database);
they only warn. The wait per Job and per rollout is `K8SA_SMOKE_TIMEOUT` seconds
(default 300).

### `deploy/k8s/images.txt` (several app images)

Without it, only the first Deployment's image is built, from `<app>/Dockerfile`. With
it, every image listed is built from the app root, loaded into kind and swapped in:

```text
# <image name as in base>  [docker build args]
myapp-api     --build-arg MAIN=./cmd/api
myapp-worker  --build-arg MAIN=./cmd/worker
```

- The name must equal an image's repository in the rendered overlay, or its last path
  segment (`myapp-api` matches `registry.example.com/myapp-api`, never `myapp-api-v2`).
- Build args are split on whitespace with no quoting; `#` starts a comment; `|` is not
  allowed. Use `-f path/Dockerfile` for another Dockerfile.

### Load and chaos (after a smoke run, same cluster)

```bash
k8sa-load  <app-path> [overlay] [--path /healthz] [--vus 10] [--rps N] [--duration 30] [--max-error-rate 0.01]
k8sa-chaos <app-path> prod [--path /healthz] [--kills 5] [--interval 10] [--mode delete|evict|rollout] [--rps 200]
k8sa-chaos --self-test     # once per cluster: can chaos see a missing readinessProbe here?
```

`k8sa-load` runs a pinned `grafana/k6` Job inside the smoke namespace against the app's
Service and prints requests, error rate, rps and p50/p95/p99 latency. A request fails on
a network error, timeout or status outside 200–399; failures are split into `timeout`,
`conn` (refused/reset — the usual restart bug) and `http` (bad status). `k8sa-chaos`
runs fixed-rate load (200 rps — availability, not capacity) while it disrupts the Deployment — `delete` random ready pods, `evict` them through the Eviction
API (honours the PDB), or `rollout` restart (exercises `maxUnavailable: 0`) — waiting
for the Deployment to be fully ready before each one. Zero failed requests (default
threshold 0) means no request was dropped across those disruptions — see below for how
much that proves. Both only use `--context kind-k8s-anything` and `smoke-*`
namespaces; pass `-n <namespace>` instead of the app path to target one directly.

| Exit | Meaning |
|---|---|
| 0 | PASS — error rate within threshold (chaos: every disruption happened under load) |
| 1 | FAIL — too many failed requests; `K8SA_FAIL` lines carry timestamps to match against the disruptions |
| 2 | usage/setup error (no smoke namespace, several Deployments without `--deployment`…) |
| 3 | INCONCLUSIVE — no result, or not every disruption happened under load; never a pass |

Chaos needs ≥ 2 ready replicas for `delete`/`evict` (use the prod overlay). With
placeholder Secrets the app's real endpoints may 500 — point `--path` at the health
endpoint and say so in the report. Only `timeout` failures on a busy shared node are
noise: re-run `k8sa-load --rps 200` alone as a baseline before blaming the manifests.
Paste the result lines into the report.

**What a chaos PASS does and doesn't prove.** On single-node kind it reliably catches
too few replicas, a bad `maxUnavailable`/PDB, and pods that are routed to long before
they listen. It is weak evidence for the readiness probe and `preStop` of a fast-booting
app. flask-redis (`evals/flask-redis/reference`), `--path /healthz`, `delete` mode:

| Template | Load | Failed requests |
|---|---|---|
| reference (probes + preStop) | 200 rps, 10 kills | 0 / 54001 |
| no readiness/startup probe | 200 rps, 5 kills | 0 / 31001 |
| no preStop | 200 rps, 10 kills | 8 / 54000 (all within 50 ms after one kill) |
| no preStop | 50 rps, 10 kills | 2 / 13500 |
| neither | 50 rps, 3 kills | **0** (PASS) |
| neither | 200 rps, 5 kills | 7 / 31001 |
| reference + `sleep 10` before gunicorn | 50 rps, 3 kills | 0 / 5451 |
| no probes + `sleep 10` before gunicorn | 50 rps, 3 kills | 852 / 5451 (FAIL) |

Why the missing probe is invisible: gunicorn's master binds the port before its worker
boots (~0.3 s), so a pod routed to early queues requests in the listen backlog instead
of refusing them. Why the missing preStop is only sometimes visible: the gap it covers
(old pod has closed its socket, kube-proxy hasn't synced — `minSyncPeriod` 1 s) is a
fraction of a second on one node; in ~1 of 10 kills a few requests land in it
(`connection reset`/`refused`). So a FAIL is real, but a PASS on a fast-booting app is
weak evidence for the probe and preStop; more `--kills` and `--rps` make it stronger.

So before trusting a PASS, run `k8sa-chaos --self-test` once per cluster: it deploys a
busybox fixture that takes 8 s to listen into a throwaway `smoke-k8sa-selftest-*`
namespace and requires chaos to PASS it with a readinessProbe + preStop (0 / 4200
failed on kind) and FAIL it without (535 / 4201 refused). Exit 0 = the harness can see a
readiness gap here; 1 = it can't, and no chaos verdict on this cluster means anything.
To test *your* app's readiness gating, make it slow to start in the smoke namespace
only — e.g. `kubectl --context kind-k8s-anything -n smoke-… patch deploy <app>` its
`command` to `sh -c 'sleep 10; exec <original CMD>'` — and re-run chaos: it must still
PASS (re-run `k8sa-smoke` afterwards to restore the real template). Report a PASS as "no dropped requests under N × mode at R rps on kind", never as
"zero-downtime proven".

## Loop

Repeat Polish ↔ Validate until clean. Paste final summaries into the report.
