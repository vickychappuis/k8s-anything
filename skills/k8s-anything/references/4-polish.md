# Stage 4 — Polish

This is where the agent earns its keep. Walk `policies/production-checklist.md` for
every workload. Defaults below; deviate when evidence says so and record why.

## Probes

- `startupProbe` for slow starters (JVM, big Python imports): generous
  `failureThreshold` × `periodSeconds`.
- `readinessProbe`: the health endpoint found in Discover. If it checks dependencies,
  readiness may; liveness must not.
- `livenessProbe`: cheap, process-only. If unsure, prefer omitting liveness over a bad one.
- No HTTP endpoint (workers): `exec` probe only if there's a meaningful check; otherwise
  none + note it.

## Resources

- Always set `requests` (cpu + memory) and a memory `limit`. CPU limit: omit by default
  (throttling), add in prod overlay only if the user's platform requires it.
- Starting points (mark as assumptions): Node/Python/Go web `100m/128Mi`,
  JVM `250m/512Mi` with `-XX:MaxRAMPercentage=75`.

## Security

Pod: `runAsNonRoot: true`, `seccompProfile: RuntimeDefault`, `fsGroup` if volumes.
Container: `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true` (+ `emptyDir`
on `/tmp` and any write path), `capabilities.drop: [ALL]`.
`automountServiceAccountToken: false` unless the app calls the k8s API.

## Config & secrets

- Non-secret env → ConfigMap via `configMapGenerator` (hash suffix ⇒ rollout on change).
- Secret env → `secret.example.yaml` with placeholder keys, excluded from
  `kustomization.yaml`; document the options (kubectl create secret, External Secrets,
  Sealed Secrets, SOPS) in the report.

## Availability & scaling (prod overlay)

- `replicas: 2+`, `PodDisruptionBudget` (`minAvailable: 1`), topology spread across nodes.
- `HorizontalPodAutoscaler` on CPU for stateless web services.
- `terminationGracePeriodSeconds` ≥ app's drain time; `preStop` sleep if behind an LB.

## Networking

- Service `ClusterIP` by default; `Ingress` (or Gateway API `HTTPRoute` if the user's
  cluster uses it) only for public web services, host as a placeholder.
- `NetworkPolicy`: default-deny ingress in namespace + allow rules derived from the
  service dependency graph from Discover.

## Images

- Base references the image by name only; overlays set tag via `images:` in kustomization.
- `imagePullPolicy` default; never `:latest` in prod overlay.
