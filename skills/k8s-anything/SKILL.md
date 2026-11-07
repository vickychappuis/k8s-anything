---
name: k8s-anything
description: Transform any application repository into a production-shaped Kubernetes deployment (Dockerfile + Kustomize base/overlays + report). Use when the user asks to "deploy this to Kubernetes", "k8sify", "containerize and generate manifests", "convert docker-compose to k8s", "make a Helm chart / Kustomize for this app", or to migrate an app (Heroku/Procfile, compose, VM, PaaS) onto Kubernetes.
---

# k8s-anything

Turn the app in the current repo (or a path the user gives) into a Kubernetes
deployment. Use existing tools for the deterministic work; use your judgment to fill
gaps and polish. Never hand-write what a tool already generates — generate, then edit.

Paths like `scripts/…`, `templates/…`, `policies/…` and `agents/…` are relative to the
k8s-anything root (in Claude Code: `${CLAUDE_PLUGIN_ROOT}`), not to the target app.

## Output contract

Write only these, inside the target app:

```text
Dockerfile, .dockerignore        # only if missing (or user asked to replace)
deploy/k8s/base/                 # kustomization.yaml + one file per resource kind/service
deploy/k8s/overlays/dev/
deploy/k8s/overlays/prod/
deploy/k8s/K8S_REPORT.md         # see references/report-template.md
```

If the user asks for Helm instead of Kustomize, produce `deploy/helm/<app>/` and
keep the same report.

## Workflow

Track these five stages as a checklist. Each stage has a playbook in `references/`;
read it when you enter the stage, not before.

1. **Discover** → [`references/1-discover.md`](references/1-discover.md)
   Run `scripts/detect.sh <app>` (from this plugin's root) for the deterministic
   fingerprint, then read the code to confirm: services, entrypoints, ports, env vars,
   backing services (DB, cache, queue), persistent state, health endpoints, migrations.
   Also read the stack note in `references/stacks/` that matches.
2. **Containerize** → [`references/2-containerize.md`](references/2-containerize.md)
   Existing Dockerfile → lint and harden it. None → generate with `docker init` /
   Buildpacks / Railpack, then refine.
3. **Translate** → [`references/3-translate.md`](references/3-translate.md)
   compose present → `kompose convert`; complex multi-service → Move2Kube; otherwise
   start from `templates/kustomize/`. Then restructure into base/overlays.
4. **Polish** → [`references/4-polish.md`](references/4-polish.md)
   Probes, resources, securityContext, config/secret split, workload kinds, HPA, PDB,
   NetworkPolicy, Ingress, labels. Checklist in `policies/production-checklist.md`.
5. **Validate** → [`references/5-validate.md`](references/5-validate.md)
   `scripts/validate.sh deploy/k8s`; fix and repeat until clean. Offer
   `scripts/smoke-kind.sh` for a real local rollout.

Then write `K8S_REPORT.md` and summarize to the user: what was generated, what was
assumed, and the open questions they must answer before prod.

## Delegation (Claude Code)

For multi-service apps, use the subagents in `agents/` in parallel per service for
Discover and Polish (`app-analyst`, `k8s-hardener`), then a single `k8s-validator`
pass over the whole output. For a single service, do it inline — subagents cost more
than they save.

## Hard rules

- Every port, env var, probe path and resource value must be traceable to evidence or
  listed as an assumption in the report.
- Never inline secret values. Generate a Secret *template* with placeholder keys and
  document how to populate it.
- Stateful backing services (Postgres, Redis, Kafka…): don't hand-roll them as
  StatefulSets for prod. Default: external/managed service via env config; for dev
  overlay, a Bitnami/official Helm chart or simple single-replica StatefulSet is fine.
  Say which you chose and why.
- Never run `kubectl apply` against a non-local context without explicit approval.
  Check `kubectl config current-context` first.
- If a tool is missing, say so, use the fallback in `references/tools.md`, and note it
  in the report.
