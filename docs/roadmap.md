# Roadmap

## v0.1 — scaffold
- [x] 5-stage skill, references, stack notes, subagents, scripts, Kustomize template

## v0.2 — correctness (current)
- [x] Self-contained skill; `bin/k8sa-*` commands; Codex manifest
- [x] Hardened scripts (detect in Python, honest validate exit codes, Docker fallbacks)
- [x] Production-correct templates (HPA owns replicas, Namespace + PSS, probes, Gateway API)
- [x] Dockerfile templates (python, node, go, jvm), built and run under the pod's security context
- [x] Eval checker + flask-redis expectations; kind smoke test verified end to end

## v0.3 — breadth
- [ ] More examples + expectations: Next.js, Spring Boot, Go multi-binary, Rails + Sidekiq, Procfile app, multi-service compose
- [ ] Automated eval runs (agent in CI on each example, scored by `evals/check.py`)
- [ ] Helm output mode (chart + `values.schema.json`)
- [ ] Codex marketplace manifest once its local-source format is confirmed

## v0.4 — reach
- [ ] MCP server exposing detect/scaffold/validate/smoke as tools
- [ ] GitOps output (Argo CD Application / Flux Kustomization)
- [ ] External Secrets / Sealed Secrets generation
- [ ] Egress NetworkPolicy generation from the dependency graph
