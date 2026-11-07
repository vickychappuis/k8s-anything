# Changelog

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
