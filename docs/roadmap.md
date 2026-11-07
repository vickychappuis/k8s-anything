# Roadmap

## v0.1 — scaffold
- [x] 5-stage skill, references, stack notes, subagents, scripts, Kustomize template

## v0.2 — correctness
- [x] Self-contained skill; `bin/k8sa-*` commands; Codex manifest
- [x] Hardened scripts (detect in Python, honest validate exit codes, Docker fallbacks)
- [x] Production-correct templates (HPA owns replicas, Namespace + PSS, probes, Gateway API)
- [x] Dockerfile templates (python, node, go, jvm), built and run under the pod's security context
- [x] Eval checker + flask-redis expectations; kind smoke test verified end to end

## v0.3 — breadth (current)
- [x] More examples + expectations: Next.js, Go multi-binary, Procfile app (Django + Celery)
- [x] General eval harness (per-service checks), `run_all.sh`, every reference run scored and smoke-tested in CI
- [x] Helm output mode (chart + `values.schema.json`)
- [x] Load and chaos tests on kind, with a self-test
- [x] Tested dev services: PostgreSQL, MySQL, RabbitMQ, MongoDB
- [ ] More examples: Spring Boot, Rails + Sidekiq
- [ ] Automated agent runs (agent in CI on each example, scored by `evals/check.py`)
- [ ] Multi-node kind for chaos, so preStop gaps show up reliably
- [ ] Codex marketplace manifest once its local-source format is confirmed

## v0.4 — reach
- [ ] MCP server exposing detect/scaffold/validate/smoke as tools
- [ ] GitOps output (Argo CD Application / Flux Kustomization)
- [ ] External Secrets / Sealed Secrets generation
- [ ] Egress NetworkPolicy generation from the dependency graph
