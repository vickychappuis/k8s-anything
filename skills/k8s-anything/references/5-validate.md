# Stage 5 — Validate

## Static

```bash
scripts/validate.sh <app>/deploy/k8s
```

Runs, per overlay (skipping missing tools with a warning):

1. `kubectl kustomize` — it builds at all.
2. `kubeconform -strict -summary` — schema-valid against the k8s version.
3. `kube-linter lint --config policies/kube-linter.yaml` — best-practice checks.
4. `trivy config` — misconfig scan (optional).

Fix every error. For lint findings you intentionally keep, add an
`ignore-check.kube-linter.io/<check>` annotation **with a reason** and list it in the
report.

## Dynamic (optional, local only)

```bash
scripts/smoke-kind.sh <app-path> [overlay]   # default overlay: dev
```

Creates/reuses a `kind` cluster named `k8s-anything`, builds and loads the image,
applies the overlay, waits for rollout, and port-forwards to hit the readiness path.
Requires Docker + kind. Never targets any other context.

## Loop

Repeat Polish ↔ Validate until static checks are clean. Paste the final summaries
into `K8S_REPORT.md`.
