# Stage 2 — Containerize

## Decision

```text
Dockerfile exists?
├─ yes → hadolint it, then harden (below). Don't rewrite unless it's broken.
└─ no  → stack well supported by `docker init`?  (node, python, go, java, rust, php, .NET)
         ├─ yes → `docker init` (interactive: answer from Discover facts), then harden
         └─ no / unusual → Buildpacks: `pack build <img> --builder paketobuildpacks/builder-jammy-base`
                           or Railpack (`railpack build .`) — no Dockerfile needed,
                           note it in the report
```

`docker init` is interactive. In non-interactive environments, write the Dockerfile
from the matching `stacks/*.md` template instead and say so.

## Hardening checklist

- Multi-stage build: build deps don't ship in the runtime image.
- Pinned base image tag (no `latest`); prefer slim/distroless/chainguard where the stack allows.
- Runs as non-root: `USER 10001` (numeric UID so `runAsNonRoot` can verify it).
- `.dockerignore` excludes `.git`, `node_modules`, `.venv`, `.env*`, build output, tests.
- Dependency layer cached before source copy.
- `EXPOSE` matches the port found in Discover.
- `CMD` in exec form, PID 1 handles SIGTERM (use `tini` or the runtime's own handling).
- No secrets in `ARG`/`ENV`.
- Writable paths limited to what the app needs (supports `readOnlyRootFilesystem` later,
  with an `emptyDir` for `/tmp`).

## Verify

```bash
hadolint Dockerfile
docker build -t <app>:dev .
trivy image --severity HIGH,CRITICAL <app>:dev   # optional
```
