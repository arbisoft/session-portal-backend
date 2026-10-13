import pytest
from rest_framework.test import APIClient

from django.core.files.storage import FileSystemStorage
from django.db import connection
from django.db.models.signals import post_save

from events.factories import UserFactory
from events.models import Event, VideoAsset
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


@pytest.fixture
def staff_client():
    """ Returns an APIClient authenticated as a staff user """
    client = APIClient()
    client.force_authenticate(user=UserFactory(is_staff=True))
    return client


@pytest.fixture
def user_client():
    """ Returns an APIClient authenticated as a regular user """
    client = APIClient()
    client.force_authenticate(user=UserFactory(is_staff=False))
    return client


@pytest.fixture
def media_storage(tmp_path, monkeypatch):
    """ Redirect video and thumbnail uploads to a temporary directory """
    for field_name in ('video_file', 'thumbnail'):
        field = VideoAsset._meta.get_field(field_name)  # pylint: disable=protected-access
        monkeypatch.setattr(field, 'storage', FileSystemStorage(location=tmp_path / field_name))
    return tmp_path
