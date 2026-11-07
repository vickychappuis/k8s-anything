---
description: Transform the current app (or a given path) into a Kubernetes deployment
argument-hint: "[app-path] [--helm] [--no-smoke]"
---

Use the `k8s-anything` skill to transform the app at `$ARGUMENTS` (default: current
directory) into a Kubernetes deployment.

- If `--helm` is present, produce a Helm chart instead of Kustomize.
- Unless `--no-smoke` is present, offer the kind smoke test at the end (ask first).

Start by running the toolchain check (`scripts/doctor.sh` from the k8s-anything plugin
root) and telling me in one line which tools are missing and what that changes.
