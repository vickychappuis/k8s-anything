# 0002 — Kustomize as default output, Helm on request

Date: 2026-11-07 · Status: accepted

## Decision
Default output is Kustomize (base + dev/prod overlays). Helm chart output only when
the user asks (`/k8sify --helm`).

## Why
Plain YAML is easier for agents to edit precisely and for humans to review; no
templating language. `kubectl apply -k` works with no extra tooling. Helm stays
available for teams that distribute charts.
