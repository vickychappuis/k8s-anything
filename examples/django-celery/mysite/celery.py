import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")

app = Celery("mysite")
app.config_from_object("django.conf:settings", namespace="CELERY")
# Beat's default scheduler persists to ./celerybeat-schedule (the working directory).
app.conf.beat_schedule = {"tick-every-30s": {"task": "mysite.celery.tick", "schedule": 30.0}}


@app.task
def tick():
    return "tick"
