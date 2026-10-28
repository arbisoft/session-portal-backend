from rest_framework import status
from rest_framework.response import Response

from django.db.models import Q
from django.shortcuts import get_object_or_404

from events.models import Event
from events.v1.serializers import UploadSessionSerializer


def media_type(request) -> str:
    """ Lower-cased request content type without parameters such as ``charset`` """
    return request.content_type.split(';')[0].strip().lower()


def session_response(session, http_status=status.HTTP_200_OK) -> Response:
    """ Session representation with the confirmed offset also exposed as a header """
    data = UploadSessionSerializer(session).data
    response = Response(data, status=http_status)
    response['Upload-Offset'] = str(data['offset'])
    response['Cache-Control'] = 'no-store'
    return response


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
