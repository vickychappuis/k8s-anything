# Stage 5 — Validate

## Static

```bash
k8sa-validate <app>/deploy/k8s
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
into a `smoke-<app>-<overlay>` namespace, and waits for Deployments/StatefulSets to
roll out. Your previous kubectl context is restored. Requires Docker, kind, python3.

### Load and chaos (after a smoke run, same cluster)

```bash
k8sa-load  <app-path> [overlay] [--path /healthz] [--vus 10] [--rps N] [--duration 30] [--max-error-rate 0.01]
k8sa-chaos <app-path> prod [--path /healthz] [--kills 5] [--interval 10] [--mode delete|evict|rollout]
```

`k8sa-load` runs a pinned `grafana/k6` Job inside the smoke namespace against the app's
Service and prints requests, error rate, rps and p50/p95/p99 latency. A request fails on
a network error, timeout or status outside 200–399; failures are split into `timeout`,
`conn` (refused/reset — the usual restart bug) and `http` (bad status). `k8sa-chaos`
runs fixed-rate load (50 rps — availability, not capacity) while it disrupts the Deployment — `delete` random ready pods, `evict` them through the Eviction
API (honours the PDB), or `rollout` restart (exercises `maxUnavailable: 0`) — waiting
for the Deployment to be fully ready before each one. Zero failed requests (default
threshold 0) means preStop, readiness, PDB and rollout strategy really give
zero-downtime restarts. Both only use `--context kind-k8s-anything` and `smoke-*`
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
noise: re-run `k8sa-load` alone as a baseline before blaming the manifests. Paste the
result lines into the report.

## Loop

Repeat Polish ↔ Validate until clean. Paste final summaries into the report.
