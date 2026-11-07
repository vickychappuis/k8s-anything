# Python

**Detect:** `pyproject.toml`, `requirements*.txt`, `Pipfile`, `uv.lock`, `poetry.lock`.
Frameworks: `django`, `flask`, `fastapi`, `starlette`, `celery`, `streamlit`.

**Template:** `assets/dockerfiles/python.Dockerfile` (venv, gunicorn, UID 10001).

**Server:** never the dev server (`app.run`, `manage.py runserver`). Flask/Django →
`gunicorn`; FastAPI → `gunicorn -k uvicorn.workers.UvicornWorker` or `uvicorn
--host 0.0.0.0`. gunicorn binds `0.0.0.0:$PORT` when `PORT` is set and reads
`WEB_CONCURRENCY` for workers — size it to the CPU request, not host cores. This also
fixes apps that hard-code `127.0.0.1` in their `__main__` block, without a source change.
If the server isn't in the requirements, the template adds it at build time; note it.

**Build:** `uv.lock` → `uv sync --frozen --no-dev`; poetry → `poetry install --only
main`. Native deps (psycopg, numpy) → `-slim`, not alpine.

**Env:** `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1` (also needed for a read-only root FS).

**Django:**
- `collectstatic --noinput` at build time, only if `django.contrib.staticfiles` is
  installed and `STATIC_ROOT` is set (it errors otherwise).
- `migrate` as a Job (see 3-translate.md).
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` (if the settings read it) must include
  the public hostname.
- **Probes vs `ALLOWED_HOSTS`:** kubelet HTTP probes send the pod IP as `Host`, which
  Django answers with 400 (`DisallowedHost`), so pods never get Ready. Add
  `httpHeaders: [{name: Host, value: localhost}]` to HTTP probes and keep `localhost`
  in `ALLOWED_HOSTS`. Don't use `ALLOWED_HOSTS=*`.
- Check how `DEBUG` defaults when unset (often `True`); set `DEBUG=False` explicitly
  in the ConfigMap.

**Celery:**
- Worker = Deployment, no Service. Pass `--concurrency` sized to the CPU request:
  prefork defaults to the **node's** core count, not the container's.
- Warm shutdown on SIGTERM finishes running tasks, so set
  `terminationGracePeriodSeconds` to the longest task.
- Beat = Deployment with `replicas: 1` and `strategy: Recreate` (a rolling update
  would run two schedulers). No HPA and no PDB.
- Beat's default schedule file is `./celerybeat-schedule` in the working directory,
  which fails on a read-only root FS ("Read-only file system", exit 1). Run it with
  `--schedule /tmp/celerybeat-schedule` on the `/tmp` emptyDir.
- Neither has a port. Skip HTTP probes and annotate kube-linter's
  `no-readiness-probe` (and `no-rolling-update-strategy` on beat) with the reason
  (5-validate.md).
- Pin `kombu` and `redis` too if `requirements.txt` doesn't. `celery[redis]` leaves
  them floating, and a new kombu can need a redis-py the lock doesn't allow
  (`VersionMismatch` at startup). This is a source change, so propose it.

**Resources:** `100m / 192Mi`, limit `512Mi` (gunicorn with 2 workers).
