---
description: Validate and polish existing Kubernetes manifests
argument-hint: "[manifests-dir]"
---

Use the `k8s-polish` skill on `$ARGUMENTS` (default: `deploy/k8s`). Start with a
baseline run of `scripts/validate.sh` from the k8s-anything plugin root, then polish
and re-validate. Show before/after finding counts.
