# Python

**Detect:** `pyproject.toml`, `requirements*.txt`, `Pipfile`, `uv.lock`, `poetry.lock`.
Framework: `django`, `flask`, `fastapi`, `starlette`, `celery`.

**Server:** never the dev server in prod. Flask/Django → `gunicorn`; FastAPI →
`uvicorn` (or `gunicorn -k uvicorn.workers.UvicornWorker`). Bind `0.0.0.0:$PORT`.
Workers ≈ CPU request-based, not host cores (`WEB_CONCURRENCY` env).

**Build:** `uv` if `uv.lock` (fast, `uv sync --frozen --no-dev`); poetry → export or
`poetry install --only main`. Multi-stage: build wheels in builder, copy venv to runtime.
Native deps (psycopg, numpy) → `-slim` base, not alpine.

**Env:** `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`.

**Django:** `collectstatic` at build time; `migrate` as a Job (not at container start);
`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` must include the Ingress host.

**Celery:** worker = Deployment, beat = Deployment with `replicas: 1` (never scale beat).

**Resources:** `100m / 192Mi` request, `512Mi` limit.
