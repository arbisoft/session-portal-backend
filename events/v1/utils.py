from django.shortcuts import get_object_or_404

from events.models import Event


def get_similar_events(event_id):
    """
    Get similar events based on the same playlist, presenter, or tags.
    Returns events in order of similarity priority.
    """
    event = get_object_or_404(Event, id=event_id)

    similar_events = Event.objects.filter(playlists__in=event.playlists.all()).exclude(id=event.id).distinct()

    if not similar_events.exists():
        similar_events = Event.objects.filter(
            presenters__user__in=event.presenters.values('user')
        ).exclude(id=event.id).distinct()

    if not similar_events.exists():
        similar_events = Event.objects.filter(tags__in=event.tags.all()).exclude(id=event.id).distinct()

    return similar_events
