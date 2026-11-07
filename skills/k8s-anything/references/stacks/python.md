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

**Django:** `collectstatic` at build time; `migrate` as a Job; `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS` must include the public hostname.

**Celery:** worker = Deployment. Beat = Deployment with `replicas: 1` and
`strategy: Recreate` (a rolling update would run two schedulers), plus an `emptyDir`
for its schedule file (`--schedule /tmp/celerybeat-schedule`).

**Resources:** `100m / 192Mi`, limit `512Mi` (gunicorn with 2 workers).
