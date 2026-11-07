# 0001 — Tools first, agents second

Date: 2026-11-07 · Status: accepted

## Context
Converting apps to Kubernetes is mostly solved for the mechanical part (kompose,
Move2Kube, docker init, Buildpacks) and for checking (kubeconform, kube-linter, Trivy).
What those tools produce is rarely production-ready: no probes, no resources, root
containers, secrets inlined, wrong workload kinds.

## Decision
k8s-anything orchestrates existing tools and adds an agentic layer for discovery
(evidence from code) and polish (production hardening). It never reimplements a
converter.

## Consequences
- Quality tracks upstream tools; we inherit their fixes.
- Every script must degrade gracefully when a tool is missing.
- The value we own is the skills, checklists, templates, and the evidence-backed report.
