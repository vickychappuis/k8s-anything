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

Jobs are waited for first and fail the test as soon as they fail (logs are printed),
except Jobs that read a placeholder Secret: those only warn. The wait per Job and per
rollout is `K8SA_SMOKE_TIMEOUT` seconds (default 300).

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

## Loop

Repeat Polish ↔ Validate until clean. Paste final summaries into the report.
