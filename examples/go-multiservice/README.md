# Example: go-multiservice

A tiny Go module with **two binaries** — `cmd/api` (HTTP API) and `cmd/worker`
(background poller) — sharing a Postgres database, plus a **naive**
`docker-compose.yml` and **no Dockerfile**. It exercises the multi-service path of
k8s-anything (Delegation, one image per binary, worker without a Service, migrations).

A good k8s-anything run should, among other things:

- build **one image per binary** (`--build-arg MAIN=./cmd/api` / `./cmd/worker`) from a
  hardened, distroless, non-root Dockerfile
- give the **worker** a Deployment with **no Service and no HTTP probes** — it listens
  on no port (cmd/worker/main.go)
- notice the api reads `PORT` (default 8080, cmd/api/main.go) while compose
  hard-codes `PORT: "9090"` and `9090:9090`: pick one port and set `PORT`, `containerPort`
  and probes consistently
- use `/healthz` for the api's probes (it never touches the database)
- turn compose's `command: sh -c "/app migrate && exec /app"` into a **migration Job**
  (`api migrate`), not a boot-time step in every api replica — and note the distroless
  image has no `sh` anyway
- treat `DATABASE_URL` as a **secret**: compose inlines `postgres://app:s3cret-pw@…`
- make Postgres dev-only (in-cluster StatefulSet) and external/managed in prod
- drop `LOG_LEVEL` (declared for the worker, never read) and `depends_on`, after
  confirming both binaries tolerate the database being down at boot (`sql.Open` is
  lazy; the worker logs and retries)

Try it: copy this folder somewhere, open Claude Code there and run `/k8s-anything:k8sify`.
Score the result with `python3 evals/check.py evals/go-multiservice <copy>`.
