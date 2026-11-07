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
bin/k8sa-detect path/to/app  # JSON fingerprint of an app
```

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
├── overlays/dev/           # + dev-only Redis/Postgres, fake dev secrets
├── overlays/prod/          # + HPA, PDB, NetworkPolicy, route
└── K8S_REPORT.md           # evidence, assumptions, open questions, checklist, validation
```

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
│   │   ├── assets/              # Kustomize template, Dockerfile templates, lint policy, report template
│   │   └── scripts/             # detect.py, scaffold, validate, smoke-kind, doctor
│   └── k8sify/                  # /k8sify entry point (user-invoked)
├── agents/                      # subagents for multi-service apps (analyst, hardener, validator)
├── examples/                    # input apps with deliberate pitfalls
├── evals/                       # expectations + checker that scores a run
└── docs/                        # architecture, roadmap, decisions
```

## Evals

```bash
cp -R examples/flask-redis /tmp/run && (run the skill on /tmp/run)
python3 evals/check.py evals/flask-redis /tmp/run
```

The checker scores properties (non-root image, source untouched, Redis dev-only, HPA
owns replicas, secrets not in ConfigMaps, validation passes, report sections and
evidence…) rather than diffing against fixed output.

## Status

v0.2 — see [`CHANGELOG.md`](CHANGELOG.md) and [`docs/roadmap.md`](docs/roadmap.md).
