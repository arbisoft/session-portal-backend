import factory
from faker import Faker

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify

from events.models import Event, EventPresenter, Playlist, Tag, VideoAsset

fake = Faker()
User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    """ Factory for creating User instances """
    class Meta:
        model = User

    email = factory.Faker("email")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    username = factory.Sequence(lambda n: f"user{n}")  # Generate unique usernames


class EventFactory(factory.django.DjangoModelFactory):
    """ Factory for creating Event instances """
    class Meta:
        model = Event

    creator = factory.SubFactory(UserFactory)
    title = factory.Faker("sentence", nb_words=4)
    slug = factory.LazyAttribute(lambda obj: slugify(obj.title))
    description = factory.Faker("paragraph")
    event_time = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(days=30))
    event_type = Event.EventType.SESSION
    status = Event.EventStatus.PUBLISHED


class PlaylistFactory(factory.django.DjangoModelFactory):
    """ Factory for creating Playlist instances """
    class Meta:
        model = Playlist

    name = factory.Sequence(lambda n: f"Playlist {n}")


class TagFactory(factory.django.DjangoModelFactory):
    """ Factory for creating Tag instances """
    class Meta:
        model = Tag

    name = factory.Sequence(lambda n: f"Tag {n}")


class VideoAssetFactory(factory.django.DjangoModelFactory):
    """ Factory for creating VideoAsset instances """
    class Meta:
        model = VideoAsset

    event = factory.SubFactory(EventFactory)
    title = factory.Faker("sentence", nb_words=3)
    video_file = None
    status = VideoAsset.VideoStatus.READY
    duration = factory.Faker("random_int", min=60, max=3600)  # Duration in seconds
    file_size = factory.Faker("random_int", min=1024, max=10485760)  # File size in bytes


class EventPresenterFactory(factory.django.DjangoModelFactory):
    """Factory for EventPresenter model"""

    class Meta:
        model = EventPresenter

    event = factory.SubFactory(EventFactory)
    user = factory.SubFactory(UserFactory)
