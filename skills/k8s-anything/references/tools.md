# Tool matrix

`k8sa-doctor` reports which of these are available, including Docker fallbacks.

| Tool | Stage | Role | Install (macOS) | Docker fallback | Without it |
|---|---|---|---|---|---|
| docker | 2, 5 | build/run images; runs fallbacks | Docker Desktop / OrbStack / colima | — | can't build or smoke test; say so |
| python3 | 1 | runs `k8sa-detect` | ships with macOS CLT / Linux | — | read the repo by hand |
| `docker init` | 2 | Dockerfile for unusual stacks (interactive) | Docker Desktop | — | `assets/dockerfiles/` |
| pack | 2 | Cloud Native Buildpacks | `brew install buildpacks/tap/pack` | — | `assets/dockerfiles/` |
| hadolint | 2 | Dockerfile lint | `brew install hadolint` | `hadolint/hadolint:v2.12.0` (`docker run --rm -i … < Dockerfile`) | checklist in 2-containerize |
| kubectl | 3–5 | `kubectl kustomize`, apply to kind | `brew install kubectl` | — | `kustomize` binary |
| kompose | 3 | compose → draft manifests | `brew install kompose` | — | hand mapping in 3-translate |
| move2kube | 3 | multi-source migration (low maintenance) | `brew install konveyor/move2kube/move2kube` | — | kompose / hand mapping |
| helm | 3 | chart output; dev backing services | `brew install helm` | — | Kustomize only |
| kubeconform | 5 | schema validation | `brew install kubeconform` | automatic in `k8sa-validate` | — |
| kube-linter | 5 | best-practice lint | `brew install kube-linter` | automatic in `k8sa-validate` | — |
| trivy | 2, 5 | config + image scan | `brew install trivy` | `K8SA_TRIVY_DOCKER=1` | skip, note in report |
| kind | 5 | local cluster smoke test | `brew install kind` | — | skip, note in report |
| k6 | 5 | `k8sa-load` / `k8sa-chaos` | not needed locally | `grafana/k6:0.54.0` runs as a Job in kind (`K8SA_K6_IMAGE` overrides) | skip, note in report |

Don't install tools without the user's OK. Prefer the Docker fallback when Docker is
running.
