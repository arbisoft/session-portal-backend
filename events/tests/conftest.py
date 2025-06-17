import pytest

from django.db import connection
from django.db.models.signals import post_save

from events.models import Event
from events.signals import set_slug_on_create


@pytest.fixture(autouse=True)
def disable_event_signals():
    """ Disable the post_save signal for Event during tests """
    post_save.disconnect(set_slug_on_create, sender=Event)
    yield
    post_save.connect(set_slug_on_create, sender=Event)


@pytest.fixture(scope='session', autouse=True)
def setup_test_database(django_db_setup, django_db_blocker):  # pylint: disable=unused-argument
    """Ensure test database has trigram extension"""
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
