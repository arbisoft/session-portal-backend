# Must stay first: .celery sets DJANGO_SETTINGS_MODULE, which init_sentry() needs to read settings.
from .celery import app as celery_app
from .sentry import init_sentry

init_sentry()

__all__ = ['celery_app']
