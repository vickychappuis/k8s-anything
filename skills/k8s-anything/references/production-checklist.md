# Production checklist (per workload)

Mark each item done / n/a / skipped-with-reason in the report.

## Image
- [ ] Pinned tag (no `latest`) in prod overlay
- [ ] Runs as numeric non-root UID
- [ ] Multi-stage, no build tooling in runtime image
- [ ] No secrets in image layers / build args

## Pod spec
- [ ] `app.kubernetes.io/name` + `component` labels; selectors match
- [ ] Dedicated ServiceAccount, `automountServiceAccountToken: false` unless needed
- [ ] `securityContext`: runAsNonRoot, seccomp RuntimeDefault
- [ ] Container: no privilege escalation, drop ALL caps, read-only root FS (+ emptyDir for writes)
- [ ] `terminationGracePeriodSeconds` ≥ drain time; app handles SIGTERM

## Health
- [ ] readinessProbe on a real endpoint (evidence)
- [ ] livenessProbe cheap and dependency-free (or deliberately omitted)
- [ ] startupProbe for slow starters

## Resources
- [ ] CPU + memory requests
- [ ] Memory limit; runtime heap sized to it (JVM/Node/Go)

## Config
- [ ] Non-secret config in ConfigMap (generator, hashed)
- [ ] Secrets referenced, never inlined; population method documented
- [ ] Binds `0.0.0.0`, port from env

## Availability (prod)
- [ ] replicas ≥ 2, PDB, topology spread
- [ ] HPA for stateless web
- [ ] RollingUpdate with `maxUnavailable: 0`

## Network
- [ ] ClusterIP Service with named port
- [ ] Ingress / HTTPRoute only for public services, TLS planned
- [ ] NetworkPolicy: default-deny + explicit allows

## Lifecycle
- [ ] Migrations as Job (or gated initContainer), not on every pod start
- [ ] Cron work as CronJob with `concurrencyPolicy: Forbid` unless safe
- [ ] Stateful deps: managed service in prod; dev-only in-cluster
