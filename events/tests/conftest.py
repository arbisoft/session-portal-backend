import pytest

from django.db.models.signals import post_save

from events.models import Event
from events.signals import set_slug_on_create


@pytest.fixture(autouse=True)
def disable_event_signals():
    """ Disable the post_save signal for Event during tests """
    post_save.disconnect(set_slug_on_create, sender=Event)
    yield
    post_save.connect(set_slug_on_create, sender=Event)
