# syntax=docker/dockerfile:1
# PORT/EXPOSE default to 8000: set both to the port found in Discover.
# Python web app (Flask/Django/FastAPI). Replace APP_MODULE (e.g. app:app,
# mysite.wsgi, or for FastAPI add: -k uvicorn.workers.UvicornWorker).
# gunicorn honors $PORT (binds 0.0.0.0:$PORT) and $WEB_CONCURRENCY by itself.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY requirements.txt .
# Add a production server only if requirements.txt lacks one; note it in the report.
RUN pip install -r requirements.txt gunicorn==23.0.0

FROM python:${PYTHON_VERSION}-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/opt/venv/bin:$PATH PORT=8000
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY . .
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--access-logfile", "-", "APP_MODULE"]
