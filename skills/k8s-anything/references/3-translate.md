# Stage 3 — Translate

Produce first-draft manifests, then restructure into the template's shape. Stage 4
fixes the details.

## Pick the path

| Input | Path |
|---|---|
| Single service, no compose | `k8sa-scaffold <app>/deploy/k8s <name> <port> [health] [registry]` — done, go to Stage 4 |
| Procfile (Heroku-style) | scaffold the `web` process, then add one workload per other process type in `base/` (`stacks/static-and-other.md`, Procfile section); add-ons → `assets/kustomize/dev-services/` in dev |
| Compose, kompose installed | scaffold the main service first, then `mkdir -p /tmp/kompose-out && kompose convert -f <compose> -o /tmp/kompose-out/` and mine its output for the other services |
| Compose, no kompose | scaffold the main service, then translate the remaining services by hand with the mapping below |
| Many services / Cloud Foundry / mixed sources | Move2Kube (`move2kube plan -s . && move2kube transform --qa-skip`) — low maintenance upstream; use as a fallback for inspiration, not as the base |
| Already has manifests or a chart | polish mode (SKILL.md) |

`kompose -o` writes a single **file** if the path doesn't exist — always create the
directory first and end the path with `/`.

After scaffolding, make it this app's: replace the sample config (`LOG_LEVEL`,
`EXAMPLE_API_KEY`) with the app's real keys or delete it, and delete files you don't
use (`secret.example.yaml` if there are no secrets, whichever of `httproute.yaml` /
`ingress.yaml` you didn't pick). Nothing without evidence stays.

The scaffold is the target shape. Tool output is raw material: copy what's right into
it, don't keep kompose's structure.

## Compose → Kustomize mapping

| Compose | Kubernetes |
|---|---|
| service with `build:` / app image | workload in `base/` (copy the scaffold's Deployment for each extra app service) |
| service with a stock image (redis, postgres…) | **dev only**: `overlays/dev/<name>.yaml` — start from `assets/kustomize/dev-services/` (`redis.yaml` and `postgres.yaml` are there and tested); others: single-replica StatefulSet + Service running as the image's own non-root UID. Prod: external service via config |
| `environment:` (non-secret) | `configMapGenerator` literals in base |
| `environment:` (secret) | `secretRef` in the Deployment + `secretGenerator` with fake values in `overlays/dev`; prod Secret created out-of-band (document in report) |
| env keys the code never reads | drop them; list in report |
| `ports:` | `containerPort` + Service port (container side only; host side is irrelevant) |
| `volumes:` named | dev backing service → `volumeClaimTemplates`; app → emptyDir (cache) or PVC (real state) or remove (state externalized) |
| `depends_on:` | nothing. Check the app tolerates the dependency being down at boot (if not, add an initContainer wait and flag it). Record the outcome in the report's "Not translated" section |
| `command:` / `entrypoint:` | container `command`/`args` |
| `healthcheck:` | evidence for probes |

## Labels

Keep the scaffold's conventions: every resource has explicit
`app.kubernetes.io/name` selectors; common labels use `includeSelectors: false`
(selectors are immutable — changing a selector label later breaks `apply`). Remove
kompose noise: `io.kompose.*` labels/annotations, `status: {}`,
`creationTimestamp: null`, empty `resources: {}`.

## Workload kind mapping

| Process | Kind |
|---|---|
| web / API | Deployment + Service |
| worker / consumer | Deployment (no Service) |
| singleton scheduler (Celery beat, Sidekiq-cron leader) | Deployment, `replicas: 1`, `strategy: Recreate` |
| scheduled task | CronJob (`concurrencyPolicy: Forbid` unless safe to overlap) |
| migrations / one-off | Job (or initContainer if it must gate rollout — say which and why) |

Migration Jobs:
- Prefer a Job over an initContainer. Every replica runs an initContainer, so
  migrations would run concurrently.
- A Job's pod template is immutable, so `kubectl apply` with a new image tag fails on
  an existing Job. Set `ttlSecondsAfterFinished` so the finished Job deletes itself
  and the next apply recreates it, or have CI delete it first. Also set
  `restartPolicy: Never` and a `backoffLimit` that covers the database still
  starting.
- Explain the release ordering (migrate, then roll out) in the report.
