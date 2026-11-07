# Stage 4 — Polish

Walk `production-checklist.md` for every workload. The scaffold already encodes the
defaults below; your job is to make them true for this app, with evidence, and record
every deviation.

## Probes

- `startupProbe` on the health path; size `failureThreshold × periodSeconds` to the
  real warm-up (JVM, big imports, migrations at boot).
- `readinessProbe` on the health path. It may check dependencies.
- `livenessProbe` must be dependency-free. Default is a TCP check on the port; use an
  HTTP path only if that endpoint never touches a dependency.
- `timeoutSeconds: 3` (the 1s default flaps under load).
- Workers with no port: no Service, no HTTP probes, no preStop. Add an `exec` probe
  only if there's a meaningful check; distroless images have no shell. Otherwise
  leave probes out. Annotate the Deployment with
  `ignore-check.kube-linter.io/no-readiness-probe` and `.../no-liveness-probe`, give
  the reason, and note it in the report. Don't add a fake
  probe.

## Resources

- Always CPU + memory `requests` and a memory `limit`. No CPU limit by default
  (throttling); add one only if the platform requires it.
- Starting points: the stack note in `stacks/` wins; otherwise `100m / 128Mi`, limit
  `512Mi`. Size the runtime heap to the limit (JVM `MaxRAMPercentage`, Node
  `--max-old-space-size`, Go `GOMEMLIMIT`). Mark all of these as assumptions.

## Security

- Pod: `runAsNonRoot`, numeric `runAsUser` matching the image, `seccompProfile:
  RuntimeDefault`, `fsGroup` if volumes.
- Container: `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`,
  `capabilities.drop: [ALL]`. Add an `emptyDir` for every path the app writes
  (`/tmp` is in the scaffold; see `stacks/` for framework-specific ones).
- `automountServiceAccountToken: false` unless the app calls the Kubernetes API.
- Namespaces carry `pod-security.kubernetes.io/enforce: restricted` (scaffold does it).

## Config & secrets

- Non-secret → `configMapGenerator` (hash suffix ⇒ rollout on change).
- Secret → `secretRef`. Base and prod never contain values. Dev uses a
  `secretGenerator` with obviously fake values. Document the prod options (kubectl
  create secret, External Secrets, Sealed Secrets, SOPS) in the report.

## Availability & scaling (prod overlay)

- **The HPA owns the replica count.** Never set `replicas` in base or prod when an
  HPA exists, or every `apply` resets autoscaling.
- PDB `minAvailable: 1` + `unhealthyPodEvictionPolicy: AlwaysAllow`.
- Topology spread across nodes and zones (scaffold does it).
- Graceful shutdown: native `preStop.sleep` (5s) so endpoints drain;
  `terminationGracePeriodSeconds` > preStop + the app's drain time.
- Singletons (schedulers, beat): `replicas: 1`, `strategy: Recreate`, no HPA, no PDB.
  Annotate `ignore-check.kube-linter.io/no-rolling-update-strategy` with the reason.
- Queue/DB-polling workers: a CPU HPA rarely fits, because backlog doesn't raise CPU.
  Set a fixed `replicas` in prod (≥ 2 if concurrent consumers are safe) plus a PDB.
  Suggest KEDA on queue depth as an option.

## Networking

- ClusterIP Service with a named port.
- Public web services get exactly one route: Gateway API `HTTPRoute` (`httproute.yaml`) by default;
  `ingress.yaml` only if the cluster has an Ingress controller and no Gateway.
  Hostnames are placeholders — list them as open questions.
- NetworkPolicy: namespace default-deny ingress + explicit allows from the dependency
  graph (scaffold allows same namespace + the gateway namespace). Egress policies only
  if the user asks: they break every outbound dependency until each is allowed.

## Images

- Base references the image by bare name; overlays set name/tag via `images:`.
- Prod: a release tag, ideally pinned by `digest:`. Never `latest`.

## Parallel hardeners

Before Polish, split the manifests so each workload has its own files
(`base/<svc>-deployment.yaml`, `overlays/prod/<svc>-prod.yaml`, `<svc>-pdb.yaml`).
Give each hardener its file list and its service profile. Only the main agent edits
the `kustomization.yaml` files: hardeners report the lines to add. Dev-only backing
services from `assets/kustomize/dev-services/` don't need a hardener.
