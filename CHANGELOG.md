# Changelog

## 0.3.0 — 2026-11-07

Built by eight parallel agents, each reviewed and fixed by a second agent, then
integrated and re-verified (evals, unit tests, kind smoke in dev and prod).

- **Examples + evals:** `nextjs-app` (no standalone output, build-time `NEXT_PUBLIC_*`),
  `go-multiservice` (api + worker, two images, migration Job, dev Postgres) and
  `django-celery` (Procfile: worker, beat singleton, release Job), each with a reference
  run. `evals/check.py` is a general harness: per-service kinds (web, worker,
  singleton, job, cronjob), several Dockerfiles, build args, emptyDir paths, `--json`,
  weighted score, strict `expect.json` validation; renders are decoded by kubectl
  offline. `evals/run_all.sh` scores every reference run.
- **Helm output mode:** `k8sa-scaffold --helm`, a chart with `values.schema.json` and
  dev/prod values matching the Kustomize defaults; `k8sa-validate` renders each values
  file (local helm or `alpine/helm`) and runs `helm lint --strict`.
- **Load and chaos:** `k8sa-load` (in-cluster k6) and `k8sa-chaos` (load while
  deleting, evicting or restarting pods; fails on any dropped request), plus
  `k8sa-chaos --self-test`, which proves the harness can see a missing readiness probe.
  The docs say what a pass on single-node kind does and doesn't prove.
- **Dev services:** tested PostgreSQL, MySQL, RabbitMQ and MongoDB templates next to
  Redis, all under Pod Security `restricted` with a read-only root; data survives pod
  restarts.
- **detect:** `services` array for monorepos, Go `cmd/*`, compose builds and Procfile
  processes; 19 parser bugs fixed (FIFO hang, BOM, section-aware TOML, EXPOSE
  continuations, compose anchors…); never reads through symlinks that leave the repo.
- **smoke:** several app images via `deploy/k8s/images.txt`; Jobs waited for first and
  failing fast with logs; placeholder Secrets carry the keys from
  `secret.example.yaml` and URL-shaped values; `K8SA_SMOKE_TIMEOUT`.
- **Skill guidance:** multi-service delegation, worker and singleton rules, migration
  Jobs (small `backoffLimit`, dev initContainer that waits for the DB), Django probe
  `Host` header, Celery concurrency and shutdown, Next.js without standalone.
- **Tests and CI:** 121 unit tests (detect, eval checker) on Python 3.9 and latest; CI
  validates Helm and dev services, scores every eval, and smoke-tests every example on
  kind in dev and prod, with load and chaos on flask-redis.

## 0.2.0 — 2026-11-07

Fixes from a five-reviewer audit (plugin conformance, REA comparison, Kubernetes
expert review, script stress tests, end-to-end dry run).

- **Layout:** the skill is self-contained (`skills/k8s-anything/{scripts,assets,references}`);
  `bin/k8sa-*` commands; `k8s-polish` merged into the main skill; `commands/`
  replaced by the user-invoked `k8sify` skill; unused subagents removed; Codex manifest.
- **Scripts:** `detect` rewritten in stdlib Python (valid JSON, CRLF, spaces, compose
  port syntaxes, no framework false positives); `validate` exits 3 INCONCLUSIVE when
  nothing ran and falls back to pinned Docker images; `scaffold` validates input and
  renders atomically; `smoke-kind` works (relative kustomize path, image from
  manifests, context restored); `doctor` never aborts.
- **Templates:** HPA owns replicas; Namespace with Pod Security `restricted` per
  overlay; TCP liveness; probe timeouts; preStop sleep; labels on pod templates and
  overlay resources; scoped NetworkPolicy; Gateway API HTTPRoute; zone spread;
  stricter kube-linter policy with a CPU-request check.
- **Instructions:** Dockerfile templates; no contradictions on labels/resources;
  explicit app-source policy; compose mapping; corrected stack advice (Next.js
  HOSTNAME, tini, Celery beat, Rails/.NET UIDs, bun.lock, React Router v7).
- **Evals:** `evals/check.py` + flask-redis expectations; reference run.

## 0.1.0 — 2026-11-07

Initial scaffold.
