# Stage 1 — Discover

Goal: a factual model of the app, with evidence, before generating anything.

## Deterministic pass

```bash
k8sa-detect <app-path>
```

JSON with: stacks, frameworks, Dockerfiles + `EXPOSE` ports, compose files, services
and container ports, Procfile processes, `.env*` keys, existing Helm/Kustomize/k8s
manifests, and whether `deploy/` already exists. It reads files, not behavior — a
starting point, not the answer.

`services` lists deployable-unit candidates, one entry per: `apps/*`, `packages/*` or
`services/*` directory with its own manifest (`sources: ["workspace"]`), Go
`cmd/<name>/` binary (`go-cmd`), compose service with a `build:` context (`compose`;
merged with the workspace entry when the context matches), Procfile process
(`procfile`), or — if none of those — the root app (`root`). Each entry has `name`,
`path`, `kind` (`web`/`worker`/`unknown`, a guess), `stack`, `frameworks`,
`dockerfile`, `ports` (`[{port, evidence: "file:line"}]`, from `EXPOSE`, compose
`ports`/`expose`, `--port`/`--bind`/`-p` flags in compose commands, Procfile lines and
`package.json` scripts, and Go listen addresses) and `evidence`. Use it to
seed the service table below and to split work across `app-analyst` subagents; confirm
every `kind` and port in the code. `packages/*` entries are often libraries, not
services — drop those that are only imported by others. Top-level keys stay
repo-wide aggregates.

If `existing_k8s_manifests`, `existing_kustomizations`, `existing_helm_charts` or
`existing_deploy_dir` is non-empty, ask whether to polish those (polish mode) or
generate fresh output.

## Agentic pass — answer each with file:line evidence

| Question | Where to look |
|---|---|
| How many deployable services? | compose services, monorepo `apps/*`, Procfile process types, several `main` entrypoints |
| Process type per service | web (listens on a port), worker (queue consumer), scheduled, one-off (migrations) |
| Port each web process binds | `listen(`, `app.run(`, `PORT` env, framework defaults (see `stacks/`) |
| Bind address | `localhost`/`127.0.0.1` breaks in a pod — can the server command override it? |
| Config the code **actually reads** | `process.env`, `os.environ`/`getenv`, `os.Getenv`, `@Value`, settings files |
| Config **declared** but never read | keys in compose `environment:` / `.env*` that no code reads → don't ship them; list in report |
| Config read but not declared | read in code with no default and no declaration → open question |
| Which config is secret? | KEY, SECRET, TOKEN, PASSWORD, DSN, or any URL that can carry credentials (`redis://:pw@`, `postgres://u:p@`) |
| Backing services | DB drivers, Redis/AMQP/Kafka clients, S3 SDKs, SMTP |
| Dependency at startup | does the app crash if the DB/cache is down at boot, or connect lazily/retry? |
| Local state | writes to disk (uploads, sqlite, caches) → volume or externalize |
| Health endpoint | `/health`, `/healthz`, `/ready`, `/up`, actuator; none → propose one (source change, see SKILL.md) |
| Startup/shutdown | migrations at boot? SIGTERM handled? long warm-up (JVM)? |
| Build needs | native deps, build args, private registries, monorepo build context, build-time public env (`NEXT_PUBLIC_*`) |

## Output of this stage

A service table (it goes in the report):

```text
service  kind    port  bind     health    config (secret*)          state  deps
api      web     8000  0.0.0.0  /healthz  DATABASE_URL*, LOG_LEVEL  none   postgres
worker   worker  -     -        -         DATABASE_URL*, REDIS_URL* none   postgres, redis
```

Unknowns go to "Open questions". Don't block on them: pick a sane default, mark it
as an assumption, move on.
