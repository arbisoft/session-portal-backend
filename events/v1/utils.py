from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from django.shortcuts import get_object_or_404

from events.models import Event, VideoAsset


def event_videos(event_slug: str) -> QuerySet[VideoAsset]:
    """
    Videos of the event with this slug, ordered so that the first row is the one the stream endpoint serves.

    SQL counterpart of ``Event.playable_video`` (``first_video(only_playable=True)``) only; ``first_video()`` without
    an argument ignores whether a video has a file. Within one event a video with a file beats one without, then
    the lowest video pk wins. Slugs are not unique and rows are ordered by event pk first, so with duplicate slugs
    this skips to a later event when the lowest-pk event has no videos, whereas ``VideoAssetStreamView`` takes
    the first event with that slug and returns 404 if it has no playable video. Callers take ``.first()`` (or a
    ``[:1]`` subquery) instead of ``get_object_or_404`` so duplicates never raise ``MultipleObjectsReturned``.
    """
    without_file = Case(
        When(Q(video_file__isnull=True) | Q(video_file=''), then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )
    return VideoAsset.objects.filter(event__slug=event_slug).order_by('event_id', without_file, 'pk')


def get_similar_events(event_slug: str) -> list[Event]:
    """
    Retrieve similar events based on playlists, presenters, and tags.
    Excludes the current event and returns a maximum of 5 latest events.
    """
    event = get_object_or_404(Event, slug=event_slug)
    exclude_current = ~Q(id=event.id)
    similarity_query = Q()
    published_filter = Q(status=Event.EventStatus.PUBLISHED)

    if event.playlists.exists():
        similarity_query |= Q(playlists__in=event.playlists.all())
    if event.presenters.exists():
        similarity_query |= Q(presenters__in=event.presenters.all())
    if event.tags.exists():
        similarity_query |= Q(tags__in=event.tags.all())

    cards = Event.objects.with_card_data()
    similar_events = cards.filter(exclude_current & similarity_query & published_filter).distinct()
    latest_events = cards.filter(exclude_current & published_filter).order_by('-event_time')[:5]

    combined_events = list(similar_events) + list(latest_events)
    unique_events = {event.id: event for event in combined_events}.values()
    results = sorted(unique_events, key=lambda e: e.event_time, reverse=True)

    return results
