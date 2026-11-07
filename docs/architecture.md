# Architecture

## Two layers

**Deterministic layer**: `skills/k8s-anything/scripts/`, exposed as `bin/k8sa-*`.
They wrap established tools. Same input → same output, testable in CI, no LLM.

**Agentic layer**: `skills/k8s-anything/SKILL.md` + `references/` (procedures), and
`agents/` (specialists for multi-service apps). It does what tools can't: read code
for evidence, choose between options, reconcile tool output with reality, explain
decisions.

The rule: **agents call tools and edit their output; they don't replace them.**

## Pipeline

| Stage | Command / asset | Reference | Subagent (multi-service) |
|---|---|---|---|
| 1 Discover | `k8sa-detect` | `1-discover.md`, `stacks/*` | `app-analyst` |
| 2 Containerize | `assets/dockerfiles/*`, docker init, pack, hadolint | `2-containerize.md` | — |
| 3 Translate | `k8sa-scaffold` (+ kompose) | `3-translate.md` | — |
| 4 Polish | — | `4-polish.md`, `production-checklist.md` | `k8s-hardener` |
| 5 Validate | `k8sa-validate`, `k8sa-smoke` | `5-validate.md` | `k8s-validator` |

## Why the skill is self-contained

Skills get installed on their own (Codex, skill registries, copied folders), not
only as part of the Claude Code plugin. Everything the skill reads or runs lives under
`skills/k8s-anything/`. `bin/` is a thin convenience layer: Claude Code puts a
plugin's `bin/` on `PATH`, so agents can run `k8sa-validate` from the target app's
directory without knowing where the plugin is installed.

## Distribution

- Claude Code: `.claude-plugin/` (skills and agents auto-discovered, `bin/` on PATH).
- Codex: `.codex-plugin/plugin.json` (`skills: ./skills`).
- Anything else: point the agent at `skills/k8s-anything/SKILL.md`.

## Quality

- `evals/`: expectations per example app + `check.py`, which scores a run on
  properties (not an exact diff).
- CI: shellcheck, scaffold → validate, detect on fixtures, eval checker on the
  reference run, kind smoke test.
