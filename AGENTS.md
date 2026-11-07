# AGENTS.md

Instructions for coding agents working **on this repo**. To *use* k8s-anything on an
app, follow [`skills/k8s-anything/SKILL.md`](skills/k8s-anything/SKILL.md) instead.

## Principles (apply to every skill, agent and script here)

- **Tools first, agents second.** If an established tool does a step
  deterministically, call it and post-process its output. Agents fill gaps and polish.
- **Evidence over guesses.** Every value in generated output cites file:line, tool
  output, or is listed as an assumption.
- **Degrade gracefully, never fake success.** Missing tool → Docker fallback → skip
  with a message. A check that didn't run is never reported as passing.
- **Self-contained skill.** Everything the skill needs lives under
  `skills/k8s-anything/`. Paths in SKILL.md and references are relative to that
  directory. `bin/` only wraps `skills/k8s-anything/scripts/`.
- **Never touch a live cluster without explicit approval.** The kind cluster created
  by `k8sa-smoke` is the only exception, and the user's kube context is restored.
- **No secrets in manifests** outside obviously fake dev values.

## Conventions

- Skills: `skills/<name>/SKILL.md` with frontmatter (`name`, `description`); keep
  SKILL.md short and push detail into `references/`.
- Subagents: `agents/<name>.md` with frontmatter (`name`, `description`, `tools`).
  Reference skill files as `${CLAUDE_PLUGIN_ROOT}/skills/k8s-anything/...`.
- Shell scripts: bash 3.2 compatible (macOS), `shellcheck` clean, quote everything.
  Anything that parses files or emits JSON is stdlib-only Python 3 instead.
- Templates must pass `k8sa-validate` after `k8sa-scaffold`.
- Commit messages: Conventional Commits, no AI co-author trailers.

## Checks before committing

```bash
shellcheck skills/k8s-anything/scripts/*.sh bin/*
bin/k8sa-scaffold /tmp/demo demo 8080 && bin/k8sa-validate /tmp/demo
bin/k8sa-detect examples/flask-redis
claude plugin validate .
```
