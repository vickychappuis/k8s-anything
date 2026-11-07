# Helm output (`--helm`)

Use only when the user asks for Helm. Kustomize stays the default
(docs/decisions/0002). Same stages, same report, same production defaults.

## Scaffold

```bash
k8sa-scaffold --helm <app>/deploy/helm <name> <port> [health] [registry]
# -> <app>/deploy/helm/<name>/  (chart from assets/helm/app/)
```

| Kustomize | Helm chart |
|---|---|
| `base/` | `values.yaml` + `templates/` (defaults are the **prod** shape, except the namespace-wide default-deny, which is opt-in so a casual install can't isolate other pods in a shared namespace) |
| `overlays/dev/` | `values-dev.yaml`: local image, `replicaCount: 1`, no HPA/PDB/NetworkPolicy/spread |
| `overlays/prod/` | `values-prod.yaml`: pinned image tag, HPA, PDB, NetworkPolicy + default-deny, one route |
| `configMapGenerator` (hash suffix) | `config:` → ConfigMap + `checksum/config` pod annotation |
| `secretRef` / dev `secretGenerator` | `existingSecret: <name>` only. The chart never takes secret values; dev creates a fake Secret with `kubectl create secret` before install |
| `namespace.yaml` (PSS restricted) | none: the chart is namespace-free. Create the namespace and label it `pod-security.kubernetes.io/enforce=restricted` (NOTES.txt says so) |
| `httproute.yaml` / `ingress.yaml` | `httpRoute.enabled` / `ingress.enabled` (both off; enabling both fails the render) |
| dev backing services | not in the chart: apply `assets/kustomize/dev-services/*` into the dev namespace |

Built in, don't remove: no `replicas` field while `autoscaling.enabled` (setting
`replicaCount` with the HPA on fails the render, as do min > max replicas and both
routes on); TCP liveness,
HTTP readiness/startup; `preStop.sleep`; restricted pod/container `securityContext`;
read-only root FS + `/tmp` emptyDir (`extraVolumes`/`extraVolumeMounts` for other
writable paths); explicit selector labels (`name` + `instance`, never changed; no
chart version on pod labels, so chart-only bumps don't roll pods); PDB
only rendered with >1 replica. `values.schema.json` rejects unknown keys, `latest`
tags and malformed digests — extend it when you add values.

## Polish

Do Stage 4 on `values*.yaml` first; touch `templates/` only for things values can't
express (extra containers, a worker Deployment). Record evidence as comments next to
the values. Install with the release named like the chart so resource names match
the Kustomize output: `helm install <name> deploy/helm/<name> -n <ns> -f values-<env>.yaml`.

## Validate

`k8sa-validate <app>/deploy/helm` (or the chart dir) runs `helm template` for the bare
defaults and once per `values-*.yaml` — local `helm`, else the pinned `alpine/helm`
image — then kubeconform,
kube-linter, trivy on the output, plus `helm lint --strict`. Charts with dependencies
need `helm dependency build` first.

Smoke on kind: `k8sa-smoke` is Kustomize-only for now. Manually: build, `kind load
docker-image <name>:dev`, create + label the namespace, create the dev Secret, then
`helm install … -f values-dev.yaml --wait` (via `alpine/helm` with
`kind get kubeconfig --internal` mounted and `--network kind` if helm isn't installed).
