from django.db.models import Case, Count, IntegerField, OuterRef, Q, QuerySet, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404

from events.models import Event, VideoAsset

# Keys must be Event many-to-many field names.
SIMILARITY_WEIGHTS = {'playlists': 3, 'presenters': 2, 'tags': 1}
FALLBACK_EVENT_COUNT = 5


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


def _shared_count(event: Event, field_name: str) -> Coalesce:
    """ Correlated count of the items in ``Event.<field_name>`` that the outer event shares with ``event`` """
    field = Event._meta.get_field(field_name)
    event_column = field.m2m_field_name()
    related_column = field.m2m_reverse_field_name()
    shared = (
        field.remote_field.through.objects
        .filter(**{event_column: OuterRef('pk'), f'{related_column}__in': getattr(event, field_name).values('pk')})
        .order_by()
        .values(event_column)
        .annotate(shared=Count('pk'))
        .values('shared')
    )
    return Coalesce(Subquery(shared, output_field=IntegerField()), 0)


def get_similar_events(event_slug: str) -> QuerySet[Event]:
    """
    Published events related to the event with this slug, most relevant first.

    Relevance is the weighted sum of shared playlists, presenters and tags (playlist 3, presenter 2, tag 1), so three
    shared tags tie one shared playlist. Ties go to the newest event, then the highest id. The current event is never
    included. Only when nothing is related are the latest published events returned instead, so the list is not
    empty. The queryset is lazy so pagination prefetches card data for one page only.
    """
    event = get_object_or_404(Event, slug=event_slug)
    candidates = Event.objects.with_card_data().filter(status=Event.EventStatus.PUBLISHED).exclude(id=event.id)

    relevance = Value(0, output_field=IntegerField())
    for field_name, weight in SIMILARITY_WEIGHTS.items():
        relevance = relevance + _shared_count(event, field_name) * weight

    similar_events = (
        candidates.annotate(relevance=relevance).filter(relevance__gt=0).order_by('-relevance', '-event_time', '-id')
    )
    if similar_events.exists():
        return similar_events
    return candidates.order_by('-event_time', '-id')[:FALLBACK_EVENT_COUNT]
