# Stage 3 — Translate

Produce first-draft manifests, then restructure into the template's shape. Stage 4
fixes the details.

## Pick the path

| Input | Path |
|---|---|
| Single service, no compose | `k8sa-scaffold <app>/deploy/k8s <name> <port> [health] [registry]` — done, go to Stage 4 |
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

## Several app services

- Scaffold once with the **project** name (it names the namespace, part-of label and
  shared ServiceAccount). Then rename the scaffolded workload to `<project>-<svc>`:
  Deployment, Service, selectors and image (`<project>-<svc>`). Do the same for the
  prod HPA, PDB, route and NetworkPolicy. Rename the files to `<svc>-*.yaml`.
- Use one image per binary or entrypoint, even when one Dockerfile builds them all with
  a build arg (`stacks/go.md`). List each image in both overlays' `images:`.
  Write `deploy/k8s/images.txt` (format in `5-validate.md`): `k8sa-smoke` builds
  from it, and it tells CI how to build each image.
- A one-off subcommand of an app binary (`api migrate`) reuses that image in a Job
  with `args`. It doesn't need an image of its own.
- Give each service only the config it reads: use a ConfigMap per service, and share a
  Secret only if the services read the same key (e.g. `DATABASE_URL`).

## Compose → Kustomize mapping

| Compose | Kubernetes |
|---|---|
| service with `build:` / app image | workload in `base/` (copy the scaffold's Deployment for each extra app service) |
| service with a stock image (redis, postgres…) | **dev only**: `overlays/dev/<name>.yaml` — start from `assets/kustomize/dev-services/` (Redis and Postgres are there and tested); others: single-replica StatefulSet + Service running as the image's own non-root UID. Prod: external service via config |
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

Compose often runs migrations in `command:` before the server starts
(`sh -c "app migrate && exec app"`). Don't copy that pattern: every replica would
migrate at once, and distroless images have no `sh`. Use a Job instead. Job pod
templates are immutable, so set `ttlSecondsAfterFinished` (or a GitOps hook) so the
next release can re-create the Job, and document that in the report. kube-linter flags
Jobs for `no-readiness-probe`. Annotate the Job with
`ignore-check.kube-linter.io/no-readiness-probe: "run-to-completion Job, no traffic"`.
Keep `backoffLimit` small (≈4) with `activeDeadlineSeconds` as the bound, so a broken
migration fails fast. In dev the in-cluster DB is created in the same apply and may
still be pulling or running initdb: patch the Job in `overlays/dev` with an
initContainer that waits for it, using the DB's own image (`pg_isready` in a loop for
Postgres). Don't raise `backoffLimit` to cover a slow start.
