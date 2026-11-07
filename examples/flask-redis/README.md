# Example: flask-redis

A tiny Flask + Redis app with a **naive** `docker-compose.yml` and **no Dockerfile** —
intended as test input. A good k8s-anything run should, among other things:

- generate a hardened Dockerfile (gunicorn, non-root) — the compose `build: .` has nothing to build yet
- notice the `127.0.0.1` bind in `app.py` and fix/flag it
- treat `SECRET_KEY` as a secret, `REDIS_URL` as config (or secret if it has credentials)
- use `/healthz` for probes
- make Redis dev-only (in-cluster) and external in prod
- drop `depends_on` and confirm the app tolerates Redis being unavailable at start

Try it: open Claude Code here and run `/k8sify`.
