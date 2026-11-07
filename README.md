# k8s-anything

### An agentic base that transforms any app into a Kubernetes deployment.

**Point your coding agent at a repo. Get back production-shaped Kubernetes manifests, with the evidence behind every decision.**

k8s-anything doesn't reinvent conversion. It orchestrates the tools that already
exist (`docker init`, Cloud Native Buildpacks, `kompose`, Kustomize, `kubeconform`,
`kube-linter`, Trivy, kind) and puts an agentic layer on top to do what those tools
can't: read the code, infer what the app actually needs, and polish the generated
output into something you'd ship.

```text
  your app ──► 1. Discover ──► 2. Containerize ──► 3. Translate ──► 4. Polish ──► 5. Validate ──► deploy/k8s/
               k8sa-detect     Dockerfile           k8sa-scaffold    agents:        k8sa-validate   + K8S_REPORT.md
               + code reading  templates / CNB      + kompose        probes, sec,   k8sa-smoke
                                                                     HPA, policies… (kind)
```

## Quick start

### Claude Code

```text
/plugin marketplace add vickychappuis/k8s-anything
/plugin install k8s-anything@k8s-anything
```

Then, in any app repo:

```text
/k8s-anything:k8sify                # new deployment
/k8s-anything:k8sify --polish       # harden manifests you already have
```

or just ask: *"Turn this app into a Kubernetes deployment with dev and prod overlays."*

### Codex and other agents

The skill is self-contained in [`skills/k8s-anything/`](skills/k8s-anything/)
(instructions, references, templates and scripts). Codex reads
[`.codex-plugin/plugin.json`](.codex-plugin/plugin.json); any other agent can be
pointed at [`skills/k8s-anything/SKILL.md`](skills/k8s-anything/SKILL.md).

### Check your toolchain

```bash
bin/k8sa-doctor              # installed tools, Docker fallbacks, current kube context
bin/k8sa-detect path/to/app  # JSON fingerprint of an app (and of each service in a monorepo)
```

| Command | Does |
|---|---|
| `k8sa-detect <app>` | stacks, frameworks, ports with file:line evidence, compose/Procfile services, env keys |
| `k8sa-scaffold [--helm] <dest> <name> <port>` | hardened Kustomize base + dev/prod overlays, or a Helm chart |
| `k8sa-validate <dir>` | kustomize build / helm template → kubeconform, kube-linter, Trivy |
| `k8sa-smoke <app> [overlay]` | build, load and roll out on a local kind cluster (several images via `deploy/k8s/images.txt`) |
| `k8sa-load <app> [overlay]` | in-cluster k6 load test: requests, error rate, p50/p95 |
| `k8sa-chaos <app> [overlay]` | load while deleting, evicting or restarting pods; fails on any dropped request |

Only `kubectl`, `python3` and Docker are really needed: kubeconform, kube-linter,
hadolint and Trivy run from pinned Docker images when they aren't installed.

## How it works

| Stage | Deterministic tools | Agentic layer |
|---|---|---|
| **1. Discover** | `k8sa-detect` | Read entrypoints, config the code actually reads, ports, bind address, deps, state — with file:line evidence |
| **2. Containerize** | `assets/dockerfiles/*`, `docker init`, `pack`, hadolint | Fix runtime issues at the container layer (e.g. a production server that binds `0.0.0.0`), non-root, read-only-FS friendly |
| **3. Translate** | `k8sa-scaffold`, `kompose` | Map each service to the right workload kind; backing services dev-only |
| **4. Polish** | — | Probes, resources, securityContext, config vs secrets, HPA, PDB, NetworkPolicy, Gateway API |
| **5. Validate** | `k8sa-validate` (kubeconform, kube-linter, Trivy), `k8sa-smoke` (kind) | Fix findings, loop until clean, write the report |

Every run produces, inside the target app:

```text
Dockerfile, .dockerignore   # if missing
deploy/k8s/
├── base/                   # app workloads
├── overlays/dev/           # + dev-only backing services, fake dev secrets
├── overlays/prod/          # + HPA, PDB, NetworkPolicy, route
└── K8S_REPORT.md           # evidence, assumptions, open questions, checklist, validation
```

Ask for Helm (`/k8sify --helm`) and you get `deploy/helm/<app>/` instead: a chart with
`values.schema.json` and `values-dev.yaml` / `values-prod.yaml`, same defaults.

Dev-only backing services come from tested templates (Redis, PostgreSQL, MySQL,
RabbitMQ, MongoDB), each verified on kind under Pod Security `restricted` with a
read-only root filesystem.

The app's source code isn't edited: needed source changes are proposed in the report.

## Repo layout

```text
.
├── .claude-plugin/              # Claude Code plugin + marketplace manifests
├── .codex-plugin/               # Codex plugin manifest
├── bin/                         # k8sa-* commands (on PATH when the plugin is enabled)
├── skills/
│   ├── k8s-anything/            # the skill, self-contained
│   │   ├── SKILL.md             # workflow + hard rules
│   │   ├── references/          # per-stage playbooks, per-stack notes, tools, checklist
│   │   ├── assets/              # Kustomize + Helm templates, dev services, Dockerfiles, lint policy, report
│   │   └── scripts/             # detect.py, scaffold, validate, smoke-kind, load, chaos, doctor
│   └── k8sify/                  # /k8sify entry point (user-invoked)
├── agents/                      # subagents for multi-service apps (analyst, hardener, validator)
├── examples/                    # input apps with deliberate pitfalls
├── evals/                       # expectations + checker that scores a run
├── tests/                       # unit tests for detect.py and the eval checker
└── docs/                        # architecture, roadmap, decisions
```

## Evals

Four example apps, each with deliberate pitfalls and a reference run:

| Example | What it exercises |
|---|---|
| [`flask-redis`](examples/flask-redis) | compose app, dev-only Redis, a `127.0.0.1` bind, a secret in compose |
| [`nextjs-app`](examples/nextjs-app) | Next.js without standalone output, build-time `NEXT_PUBLIC_*`, a server-only secret |
| [`go-multiservice`](examples/go-multiservice) | api + worker from one module, two images, a migration Job, dev Postgres |
| [`django-celery`](examples/django-celery) | Heroku Procfile, Celery worker, beat as a singleton, release as a Job |

```bash
cp -R examples/flask-redis /tmp/run && (run the skill on /tmp/run)
python3 evals/check.py evals/flask-redis /tmp/run   # score one run
evals/run_all.sh                                    # score every reference run
python3 -m unittest discover -s tests               # unit tests
```

The checker scores properties per workload (non-root image, source untouched, backing
services dev-only, HPA owns replicas, workers have no Service, singletons are never
scaled, secrets not in ConfigMaps, validation passes, report evidence…) rather than
diffing against fixed output. The `expect.json` schema is in
[`evals/README.md`](evals/README.md). CI scores every reference run and smoke-tests
each one on kind, in dev and prod.

## Status

v0.3 — see [`CHANGELOG.md`](CHANGELOG.md) and [`docs/roadmap.md`](docs/roadmap.md).
