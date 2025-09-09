from django.db.models import Q
from django.shortcuts import get_object_or_404

from events.models import Event


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

    similar_events = Event.objects.filter(exclude_current & similarity_query & published_filter).distinct()
    latest_events = Event.objects.filter(exclude_current & published_filter).order_by('-event_time')[:5]

    combined_events = list(similar_events) + list(latest_events)
    unique_events = {event.id: event for event in combined_events}.values()
    results = sorted(unique_events, key=lambda e: e.event_time, reverse=True)

    return results
