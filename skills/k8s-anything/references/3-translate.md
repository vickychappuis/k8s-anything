# Stage 3 — Translate

Produce first-draft manifests with a tool, then restructure. The draft will be crude;
Stage 4 fixes it.

## Pick the translator

| Input | Tool | Command |
|---|---|---|
| `docker-compose.yml` / `compose.yaml` | kompose | `kompose convert -f compose.yaml -o /tmp/kompose-out` |
| Multi-service repo, Cloud Foundry, mixed sources | Move2Kube | `move2kube plan -s . && move2kube transform --qa-skip` |
| Single service, no compose | template | `scripts/scaffold.sh <app>/deploy/k8s <name> <port> [health] [registry]` |
| Already has Helm chart / manifests | none | skip to Stage 4 and polish what exists |

## Restructure into Kustomize

1. Move tool output into `deploy/k8s/base/`, one file per resource
   (`<service>-deployment.yaml`, `<service>-service.yaml`, …).
2. Delete tool noise: `kompose.*` annotations, `status: {}`, `creationTimestamp: null`,
   empty `resources: {}`.
3. Replace kompose's `io.kompose.service` labels with the standard set:
   `app.kubernetes.io/name`, `app.kubernetes.io/component`, `app.kubernetes.io/part-of`.
   Put common labels in `kustomization.yaml` (`labels:` with `includeSelectors: true`).
4. Compose `environment:` → ConfigMap (non-secret) + Secret template (secret).
5. Compose `volumes:` → decide per Discover: emptyDir (cache), PVC (real state), or
   remove (state externalized).
6. Compose `depends_on:` → nothing in k8s. Apps must retry connections; if they don't,
   add an initContainer that waits, and flag it.
7. Write `overlays/dev` and `overlays/prod` from the template overlays.

## Workload kind mapping

| Process | Kind |
|---|---|
| web / API | Deployment + Service |
| worker / consumer | Deployment (no Service) |
| scheduled | CronJob |
| migrations / one-off | Job (or initContainer if it must gate rollout — say which) |
| database in dev only | StatefulSet + headless Service, or Helm chart dependency |
