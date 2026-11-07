# Architecture

## Two layers

**Deterministic layer** — `scripts/` wrapping established tools. Same input → same
output. Cheap, testable in CI, no LLM.

**Agentic layer** — `skills/` (procedures + references) and `agents/` (stage
specialists). Does what tools can't: read code for evidence, choose between options,
reconcile tool output with reality, explain decisions.

The rule: **agents call tools and edit their output; they don't replace them.**

## Pipeline

| Stage | Script | Skill reference | Subagent |
|---|---|---|---|
| 1 Discover | `detect.sh` | `1-discover.md`, `stacks/*` | `app-analyst` |
| 2 Containerize | (docker init / pack / hadolint) | `2-containerize.md` | `containerizer` |
| 3 Translate | `scaffold.sh` (+ kompose / move2kube) | `3-translate.md` | `manifest-translator` |
| 4 Polish | — | `4-polish.md`, `policies/production-checklist.md` | `k8s-hardener` |
| 5 Validate | `validate.sh`, `smoke-kind.sh` | `5-validate.md` | `k8s-validator` |

## Distribution

- Claude Code plugin: `.claude-plugin/` (skills, agents, commands auto-discovered).
- Other agents: `AGENTS.md` + `.agents/skills` (symlink to `skills/`).
- Future: MCP server exposing `detect`, `scaffold`, `validate`, `smoke` as tools
  (see roadmap).
