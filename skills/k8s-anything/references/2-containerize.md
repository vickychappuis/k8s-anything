# Stage 2 — Containerize

## Decision

```text
Dockerfile exists?
├─ yes → lint (hadolint), harden per the checklist below. Don't rewrite a working one.
└─ no  → start from assets/dockerfiles/<stack>.Dockerfile (python, node, go, jvm)
         ├─ stack not covered → `docker init` if you can answer its prompts
         │   interactively, else Buildpacks (`pack build <img> --builder
         │   paketobuildpacks/builder-jammy-base`) and note it in the report
         └─ JVM → prefer the framework's tooling (spring-boot:build-image, Jib, Quarkus)
```

Copy `assets/dockerfiles/dockerignore` to the app as `.dockerignore` if missing.
The templates already run as UID 10001, which matches `assets/kustomize`. If the image
uses another user (Rails 1000, .NET 1654), change `runAsUser`/`runAsGroup`/`fsGroup`
in the Deployment to match.

Fix runtime problems **in the container layer, not app source**: e.g. a
`127.0.0.1` bind in a dev server is solved by running a production server that binds
`0.0.0.0:$PORT` (gunicorn, uvicorn, `next start -H 0.0.0.0`).

## Hardening checklist

- Multi-stage: build tooling doesn't ship in the runtime image.
- Pinned base tag (no `latest`); slim/distroless where the stack allows.
- Numeric non-root `USER` (so `runAsNonRoot` can verify it).
- Dependency layer cached before copying source.
- `EXPOSE` matches the port from Discover; app reads `PORT`.
- Exec-form `CMD`/`ENTRYPOINT`; PID 1 forwards SIGTERM (tini in the image when the
  runtime doesn't handle it — `docker run --init` does nothing in Kubernetes).
- No secrets in `ARG`/`ENV`.
- Writes only to `/tmp` or declared paths (so `readOnlyRootFilesystem` works with
  `emptyDir` mounts).

## Verify

```bash
hadolint Dockerfile        # or: docker run --rm -i hadolint/hadolint:v2.12.0 < Dockerfile
docker build -t <app>:dev .
docker run --rm --read-only --tmpfs /tmp --user 10001:10001 --cap-drop ALL -e PORT=<port> -p <port>:<port> <app>:dev
```

The last command approximates the pod's security context. If it fails here, it
fails in the cluster.
