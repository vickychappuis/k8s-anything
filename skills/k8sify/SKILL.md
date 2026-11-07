---
name: k8sify
description: Transform the current app (or a given path) into a Kubernetes deployment, or polish existing manifests with --polish.
argument-hint: "[app-path] [--helm] [--polish] [--no-smoke]"
disable-model-invocation: true
---

Arguments: `$ARGUMENTS`

Parse them: the first token that doesn't start with `--` is the app path (default:
current directory). Flags:

- `--helm` — produce a Helm chart instead of Kustomize.
- `--polish` — the app already has manifests; run the "Polish existing manifests" mode.
- `--no-smoke` — don't offer the kind smoke test at the end.

Then follow the `k8s-anything` skill on that path. Unless `--no-smoke` is set, ask
before running `k8sa-smoke` at the end.
