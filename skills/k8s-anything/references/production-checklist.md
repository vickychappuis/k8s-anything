# Production checklist (per workload)

Copy into the report's "Checklist" section and mark each item
**done / n/a / skipped (why)**.

## Image
- [ ] Release tag in prod overlay, ideally pinned by digest; never `latest`
- [ ] Numeric non-root UID, matching the pod's `runAsUser`
- [ ] Multi-stage; no build tooling in the runtime image
- [ ] No secrets in layers or build args
- [ ] PID 1 forwards SIGTERM (runtime or tini)

## Pod spec
- [ ] `app.kubernetes.io/name` + `component` labels; explicit selectors match
- [ ] Dedicated ServiceAccount; token not mounted unless needed
- [ ] runAsNonRoot, seccomp RuntimeDefault
- [ ] No privilege escalation, drop ALL caps, read-only root FS + emptyDir per write path
- [ ] preStop sleep + `terminationGracePeriodSeconds` ≥ drain time

## Health
- [ ] startupProbe sized to real warm-up
- [ ] readinessProbe on an evidenced endpoint
- [ ] livenessProbe dependency-free (TCP or a pure liveness path) or deliberately omitted
- [ ] Probe timeouts ≥ 3s

## Resources
- [ ] CPU + memory requests
- [ ] Memory limit; runtime heap sized to it

## Config
- [ ] Non-secret config in a hashed ConfigMap
- [ ] Secrets referenced, never inlined outside dev; prod population documented
- [ ] Declared-but-unread env keys dropped
- [ ] Binds `0.0.0.0`; port from env

## Availability (prod)
- [ ] HPA owns replicas (no `replicas` field), min ≥ 2 — or singleton with Recreate
- [ ] PDB with `unhealthyPodEvictionPolicy: AlwaysAllow`
- [ ] Topology spread across nodes and zones
- [ ] RollingUpdate `maxUnavailable: 0`

## Network
- [ ] ClusterIP Service with named port
- [ ] HTTPRoute (or Ingress) only for public services; hostnames + TLS listed as open questions
- [ ] NetworkPolicy default-deny ingress + explicit allows

## Namespace
- [ ] Namespace object per overlay with Pod Security `restricted` labels

## Lifecycle
- [ ] Migrations as a Job (or a gated initContainer, with the reason)
- [ ] CronJobs with `concurrencyPolicy: Forbid` unless overlap is safe
- [ ] Stateful dependencies in-cluster only in dev; managed/external in prod
