# Roadmap

## v0.1 — scaffold (now)
- [x] 5-stage skill + references, per-stack notes
- [x] Stage subagents, `/k8sify`, `/k8s-validate`
- [x] `doctor`, `detect`, `scaffold`, `validate`, `smoke-kind` scripts
- [x] Hardened Kustomize template, kube-linter policy, prod checklist
- [x] Example app (flask-redis)

## v0.2 — prove it end-to-end
- [ ] Run on `examples/flask-redis`, commit expected output as a golden fixture
- [ ] More examples: Next.js, Spring Boot, Go multi-binary, Rails + Sidekiq, Procfile app
- [ ] Helm output mode (chart template + values schema)
- [ ] Eval harness: score runs against fixtures (validate pass, checklist coverage, evidence count)

## v0.3 — reach
- [ ] MCP server (`k8s-anything-mcp`) exposing scripts as tools
- [ ] Codex / Cursor / Gemini plugin manifests
- [ ] GitOps output (Argo CD Application / Flux Kustomization)
- [ ] External Secrets / Sealed Secrets generation
- [ ] Gateway API (`HTTPRoute`) option
