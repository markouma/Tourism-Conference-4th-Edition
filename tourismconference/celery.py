# tourismconference/celery.py
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tourismconference.settings")

app = Celery("tourismconference")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()  # auto-find tasks.py in INSTALLED_APPS
