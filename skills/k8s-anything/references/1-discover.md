# Stage 1 — Discover

Goal: a factual model of the app, with evidence, before generating anything.

## Deterministic pass

```bash
scripts/detect.sh <app-path> > /tmp/fingerprint.json
```

It reports: detected stacks (by manifest files), Dockerfiles, compose files,
Procfile, existing k8s/Helm/Kustomize, `EXPOSE` ports, compose ports, `.env*` keys,
and framework hints. Treat it as a starting point — it reads files, not behavior.

## Agentic pass — answer each with file:line evidence

| Question | Where to look |
|---|---|
| How many deployable services? | compose services, monorepo `apps/*`, Procfile process types, multiple `main` entrypoints |
| Process type per service | web (listens on port), worker (queue consumer), cron/scheduled, one-off (migrations) |
| Port each web process binds | `listen(`, `app.run(`, `PORT` env, framework defaults (see `stacks/`) |
| Does it bind `0.0.0.0`? | `localhost`/`127.0.0.1` binds break in a pod — flag and fix |
| Config surface | every env var read (`process.env`, `os.environ`, `os.Getenv`, `@Value`, `.env.example`) |
| Which config is secret? | names containing KEY, SECRET, TOKEN, PASSWORD, DSN, URL-with-credentials |
| Backing services | DB drivers, Redis/AMQP/Kafka clients, S3 SDKs, SMTP |
| Local state | writes to disk (uploads, sqlite, caches) → needs volume or externalization |
| Health endpoint | `/health`, `/healthz`, `/ready`, actuator; if none, propose adding one |
| Startup/shutdown | migrations at boot? handles SIGTERM? long warm-up (JVM)? |
| Build needs | native deps, build args, private registries, monorepo build context |

## Output of this stage

A short service table (keep it for the report):

```text
service  kind     port  health      env (secret*)                 state      deps
api      web      8000  /healthz    DATABASE_URL*, LOG_LEVEL       none       postgres
worker   worker   -     -           DATABASE_URL*, REDIS_URL*      none       postgres, redis
```

Unknowns go to an "Open questions" list. Don't block on them — pick a sane default,
mark it as an assumption, move on.
