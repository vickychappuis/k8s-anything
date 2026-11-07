---
name: k8s-polish
description: Harden and clean up existing Kubernetes manifests, Kustomize or Helm output (e.g. raw kompose output, hand-written YAML, a chart scaffold) to production quality — probes, resources, securityContext, config/secret split, PDB/HPA, NetworkPolicy, labels — and validate them. Use when the user already has manifests and asks to "review", "harden", "productionize", "clean up" or "lint" them.
---

# k8s-polish

Stages 4 + 5 of `k8s-anything`, standalone, for manifests that already exist.

1. Locate the manifests (raw YAML dir, `kustomization.yaml`, or Helm chart — for Helm,
   render with `helm template` to review, but edit `values.yaml`/templates, not output).
2. Read the app code just enough to ground probe paths, ports, and secret-vs-config
   decisions (see `../k8s-anything/references/1-discover.md`, agentic pass).
3. Run `scripts/validate.sh <dir>` first to get a baseline of findings.
4. Apply `../k8s-anything/references/4-polish.md` and walk
   `policies/production-checklist.md` per workload.
5. Re-validate until clean. Show the user a before/after findings count and a short
   list of changes with reasons. Preserve the user's structure and naming — polish,
   don't rewrite.
