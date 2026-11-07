# syntax=docker/dockerfile:1
# Django + Celery (Heroku-style Procfile). Generated from k8s-anything python.Dockerfile.
# One image for every Procfile process type; the default CMD is the `web` process
# (Procfile:1). worker/beat/release override `command` in their manifests.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY requirements.txt .
# gunicorn is already pinned in requirements.txt:2, so nothing is added here.
RUN pip install -r requirements.txt

FROM python:${PYTHON_VERSION}-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/opt/venv/bin:$PATH PORT=8000 \
    DJANGO_SETTINGS_MODULE=mysite.settings
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY . .
# No collectstatic: django.contrib.staticfiles isn't installed (mysite/settings.py:9).
USER 10001:10001
EXPOSE 8000
# Procfile:1 — gunicorn binds 0.0.0.0:$PORT and reads $WEB_CONCURRENCY.
CMD ["gunicorn", "--log-file", "-", "--access-logfile", "-", "mysite.wsgi"]
