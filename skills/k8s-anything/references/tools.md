# Tool matrix

What each underlying tool is for, and the fallback when it's missing.
`scripts/doctor.sh` checks all of these.

| Tool | Stage | Role | Install (macOS) | Fallback if missing |
|---|---|---|---|---|
| docker | 2, 5 | build images | Docker Desktop / OrbStack / colima | buildpacks via `pack` still needs a daemon → ask user |
| `docker init` | 2 | scaffold Dockerfile per stack | included in Docker Desktop | `stacks/*.md` templates |
| pack | 2 | Cloud Native Buildpacks | `brew install buildpacks/tap/pack` | Dockerfile from templates |
| railpack | 2 | zero-config image builds | see railpack.com | Dockerfile from templates |
| hadolint | 2 | Dockerfile lint | `brew install hadolint` | manual checklist in 2-containerize |
| kompose | 3 | compose → manifests | `brew install kompose` | translate compose by hand using 3-translate mapping |
| move2kube | 3 | multi-source migration | `brew install konveyor/move2kube/move2kube` | kompose / templates |
| kubectl | 3–5 | `kubectl kustomize`, apply to kind | `brew install kubectl` | `kustomize` binary |
| helm | 3 | when user wants a chart; backing services in dev | `brew install helm` | Kustomize only |
| kubeconform | 5 | schema validation | `brew install kubeconform` | `kubectl apply --dry-run=client` (weaker) |
| kube-linter | 5 | best-practice lint | `brew install kube-linter` | `policies/production-checklist.md` by hand |
| trivy | 2, 5 | image + config scan | `brew install trivy` | skip, note in report |
| kind | 5 | local cluster smoke test | `brew install kind` | k3d / minikube / skip |

## Not used (and why)

- **Hand-written conversion scripts** — kompose/Move2Kube cover it; we polish their output.
- **Paid/hosted generators** — this repo must work fully offline/local.
