# AGENTS.md

Instructions for coding agents (Claude Code, Codex, Cursor, Gemini CLI, …).

## Two modes

1. **Using k8s-anything on a target app** — follow
   [`skills/k8s-anything/SKILL.md`](skills/k8s-anything/SKILL.md). Write output only
   under the target app's `deploy/k8s/` (plus a Dockerfile/.dockerignore if missing).
2. **Developing k8s-anything itself** — the rules below.

## Principles (apply to every skill, agent and script here)

- **Tools first, agents second.** If an established tool does a step
  deterministically, call it and post-process its output. Agents fill gaps and polish;
  they don't hand-write what `kompose` or `docker init` already produce.
- **Evidence over guesses.** Every port, env var, probe path and resource number in the
  output must cite where it came from (file:line, tool output, or "assumption"). These go
  in `K8S_REPORT.md`.
- **Degrade gracefully.** Every script must work when an optional tool is missing: warn,
  skip, and say what was skipped. Never fail silently.
- **Never touch a live cluster without explicit approval.** Local `kind`/`k3d` clusters
  created by `scripts/smoke-kind.sh` are the only exception.
- **No secrets in manifests.** Secrets are referenced (Secret / ExternalSecret /
  SealedSecret), never inlined.

## Conventions

- Skills: `skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`) and
  optional `references/*.md`. Keep SKILL.md short; push detail into references.
- Subagents: `agents/<name>.md` with frontmatter (`name`, `description`, `tools`).
- Scripts: POSIX-ish bash, macOS (bash 3.2) compatible, `set -euo pipefail`, pass
  `shellcheck`.
- Manifests/templates: must pass `kubeconform -strict` and `kube-linter` with
  `policies/kube-linter.yaml`.

## Checks before committing

```bash
shellcheck scripts/*.sh
./scripts/validate.sh templates/kustomize
```
