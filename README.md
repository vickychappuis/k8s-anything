# k8s-anything

### An agentic base that transforms any app into a Kubernetes deployment.

**Point your coding agent at a repo. Get back production-shaped Kubernetes manifests, with the evidence behind every decision.**

k8s-anything does not reinvent conversion. It orchestrates the tools that already
exist (`docker init`, Cloud Native Buildpacks, `kompose`, Move2Kube, Helm,
Kustomize, `kubeconform`, `kube-linter`, Trivy, kind) and puts an agentic layer
on top to do what those tools can't: read the code, infer what the app actually
needs, and polish the generated output into something you'd ship.

```text
  your app ──► 1. Discover ──► 2. Containerize ──► 3. Translate ──► 4. Polish ──► 5. Validate ──► deploy/k8s/
               (fingerprint)   (Dockerfile/CNB)    (kompose/M2K/    (agents:      (kubeconform,   + K8S_REPORT.md
                                                    templates)       probes, sec,   kube-linter,
                                                                     resources…)    trivy, kind)
```

## Quick start

### As a Claude Code plugin

```bash
# from inside Claude Code
/plugin marketplace add vickychappuis/k8s-anything
/plugin install k8s-anything@k8s-anything
```

Then, in any app repo:

```text
/k8sify
```

or just ask: *"Turn this app into a Kubernetes deployment with dev and prod overlays."*

### Other agents (Codex, Cursor, Gemini CLI…)

Skills live in [`skills/`](skills/) (also exposed as `.agents/skills/`). Point your
agent at [`AGENTS.md`](AGENTS.md) and the
[`k8s-anything` skill](skills/k8s-anything/SKILL.md).

### Check your toolchain

```bash
./scripts/doctor.sh          # which underlying tools are installed, how to get the rest
./scripts/detect.sh path/to/app   # deterministic fingerprint of the app (JSON)
```

## How it works

| Stage | Deterministic tools (do the heavy lifting) | Agentic layer (makes it right) |
|---|---|---|
| **1. Discover** | `scripts/detect.sh`, existing Dockerfile/compose/Procfile | Read entrypoints, config loading, ports, env vars, external deps, state |
| **2. Containerize** | existing Dockerfile → `hadolint`; else `docker init`, `pack` (Buildpacks), Railpack | Multi-stage, non-root, pinned base, `.dockerignore`, healthcheck endpoint |
| **3. Translate** | `kompose` (compose), Move2Kube (multi-service), `templates/kustomize` | Map each service to the right workload kind (Deployment / StatefulSet / Job / CronJob) |
| **4. Polish** | — | Probes, requests/limits, securityContext, ConfigMap vs Secret split, HPA, PDB, NetworkPolicy, labels, Ingress |
| **5. Validate** | `kubeconform`, `kube-linter`, `trivy config`, `kind` smoke test | Fix findings, loop until clean, write the report |

Every run produces, inside the target app:

```text
deploy/k8s/
├── base/                 # Kustomize base (workloads, services, config)
├── overlays/dev|prod/    # environment deltas
└── K8S_REPORT.md         # evidence, assumptions, open questions, validation output
```

## Repo layout

```text
.
├── AGENTS.md                     # instructions for any coding agent working in/with this repo
├── .claude-plugin/               # Claude Code plugin + marketplace manifests
├── skills/
│   ├── k8s-anything/             # main orchestrating skill (5-stage workflow)
│   │   ├── SKILL.md
│   │   └── references/           # per-stage playbooks, tool matrix, per-stack notes
│   └── k8s-polish/               # standalone skill: harden existing manifests
├── agents/                       # specialist subagents (one per stage)
├── commands/                     # slash commands (/k8sify, /k8s-validate)
├── scripts/                      # deterministic wrappers around existing tools
├── templates/kustomize/          # hardened base + dev/prod overlays
├── policies/                     # kube-linter config, production checklist
├── examples/                     # sample apps to test the pipeline end-to-end
└── docs/                         # architecture, roadmap, decisions
```

## Status

Early scaffold (v0.1). See [`docs/roadmap.md`](docs/roadmap.md).
