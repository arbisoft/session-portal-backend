import os
from celery import Celery
from django.conf import settings


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arbisoft_sessions_portal.settings.base')

app = Celery('arbisoft_sessions_portal')

app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks(settings.INSTALLED_APPS)
