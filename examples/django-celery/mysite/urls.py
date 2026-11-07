from django.contrib.auth.models import User
from django.http import JsonResponse
from django.urls import path

from .celery import tick


def index(request):
    return JsonResponse({"users": User.objects.count(), "task": tick.delay().id})


def healthz(request):
    return JsonResponse({"ok": True})


urlpatterns = [path("", index), path("healthz", healthz)]
