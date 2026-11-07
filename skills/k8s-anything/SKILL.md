---
name: k8s-anything
description: Transform any application repository into a production-shaped Kubernetes deployment (Dockerfile + Kustomize base/overlays + evidence report), or harden existing Kubernetes manifests. Use when the user asks to "deploy this to Kubernetes", "k8sify", "containerize and generate manifests", "convert docker-compose to k8s", "make Kustomize/Helm for this app", migrate an app (Heroku/Procfile, compose, VM, PaaS) onto Kubernetes, or to review/harden/productionize/lint existing manifests.
---

# k8s-anything

Turn the app in the current repo (or a path the user gives) into a Kubernetes
deployment. Existing tools do the deterministic work; you fill gaps and polish.
Never hand-write what a tool already generates — generate, then edit.

## Helper commands

| Command | Does |
|---|---|
| `k8sa-doctor` | which underlying tools are installed; Docker-image fallbacks |
| `k8sa-detect <app>` | JSON fingerprint of the app (stacks, ports, compose, env, existing k8s) |
| `k8sa-scaffold [--helm] <dest> <name> <port> [health] [registry]` | hardened Kustomize base + dev/prod overlays (`--helm`: chart in `<dest>/<name>/`) |
| `k8sa-validate <dir>` | kustomize build or `helm template` per values file + kubeconform + kube-linter + trivy |
| `k8sa-smoke <app> [overlay]` | build, load and roll out on a local kind cluster |

In Claude Code they're on `PATH` while the plugin is enabled. Anywhere else, run
`<this skill's directory>/scripts/<name>.sh` (`smoke` → `smoke-kind.sh`). Other paths
below (`assets/`, `references/`) are relative to this skill's directory.

## Modes

- **New deployment** (no manifests yet) → full workflow below.
- **Polish existing manifests** (raw YAML, Kustomize, or Helm) → run `k8sa-validate`
  for a baseline, then stages 4–5 only. Preserve the user's structure and naming;
  for Helm, edit `values.yaml`/templates, never rendered output. Show before/after
  finding counts.

## Output contract

```text
Dockerfile, .dockerignore        # only if missing (or user asked to replace)
deploy/k8s/base/                 # app workloads, shared by all environments
deploy/k8s/overlays/dev/         # + dev-only backing services, dev secretGenerator
deploy/k8s/overlays/prod/        # + PDB, HPA, NetworkPolicy, route
deploy/k8s/K8S_REPORT.md         # from assets/report-template.md
```

Helm requested (`--helm`) → `deploy/helm/<app>/` (chart + `values-dev.yaml` /
`values-prod.yaml`) instead of `deploy/k8s/base|overlays`, same report. Follow
`references/helm.md` for scaffold, polish and validate differences.

**App source code:** don't edit it by default. Solve what you can at the
container/manifest level (server command, env, flags). If a source change is truly
required (e.g. a hard-coded `127.0.0.1` bind with no override), propose the diff to the
user and list it in the report; apply it only if they agree.

## Workflow

0. `k8sa-doctor`. Tell the user in one line which tools are missing and which
   fallback you'll use (`references/tools.md`).
1. **Discover** → `references/1-discover.md` and the matching `references/stacks/*.md`.
2. **Containerize** → `references/2-containerize.md`; Dockerfile templates in `assets/dockerfiles/`.
3. **Translate** → `references/3-translate.md`.
4. **Polish** → `references/4-polish.md`; walk `references/production-checklist.md` per workload.
5. **Validate** → `references/5-validate.md`. Loop 4↔5 until clean.

Read each reference when you enter its stage, not before. Then fill the report and
tell the user: what was generated, what was assumed, what they must answer before prod.

## Delegation (Claude Code)

Multi-service apps: one `app-analyst` subagent per service in parallel for Discover,
one `k8s-hardener` per workload for Polish, then one `k8s-validator` over everything.
Single service: do it inline — subagents cost more than they save.

## Hard rules

- Every port, env var, probe path and resource value is traceable to evidence
  (file:line or tool output) or listed as an assumption in the report.
- Never inline secret values in base or prod. Dev may use a `secretGenerator` with
  obviously fake values.
- Stateful backing services (Postgres, Redis, Kafka…) run in-cluster **only in the dev
  overlay**. Prod points at an external/managed service via config.
- Validation that ran zero checks is **INCONCLUSIVE, not PASS**. Never report it as passing.
- When this says to ask and nobody can answer (non-interactive run), take the
  conservative branch — don't edit source, don't run the smoke test, don't overwrite
  existing manifests — and record the decision in the report.
- Never `kubectl apply` to a non-kind context without explicit approval. Check
  `kubectl config current-context` first.
