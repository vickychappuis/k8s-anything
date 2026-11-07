# syntax=docker/dockerfile:1
# Python web app (Flask). Generated from k8s-anything python.Dockerfile template.
# Entrypoint: app:app (app.py:6). The app.py __main__ block binds 127.0.0.1 (app.py:21);
# gunicorn replaces it and binds 0.0.0.0:$PORT, honoring $WEB_CONCURRENCY.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY requirements.txt .
# requirements.txt has no production server, so gunicorn is added here (see K8S_REPORT.md).
RUN pip install -r requirements.txt gunicorn==23.0.0

FROM python:${PYTHON_VERSION}-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/opt/venv/bin:$PATH PORT=5000
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY . .
USER 10001:10001
EXPOSE 5000
CMD ["gunicorn", "--access-logfile", "-", "app:app"]
