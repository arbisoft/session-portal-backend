from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404

from events.models import Event, Playlist, Tag, VideoAsset
from events.v1.filters import EventFilter
from events.v1.pagination import CustomPageNumberPagination
from events.v1.serializers import EventSerializer, PlaylistListSerializer, TagListSerializer, VideoAssetSerializer


class EventTypeListView(APIView):
    """ View for listing the event types """

    @extend_schema(
        responses={
            200: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "example": "SESSION"},
                        "key": {"type": "string", "example": "session"}
                    }
                },
                "example": [
                    {"label": "SESSION", "key": "session"}
                ]
            }
        }
    )
    def get(self, request, *args, **kwargs):
        """ Get the event types """
        event_types = [
            {"label": choice[0], "key": choice[1]}
            for choice in Event.EventType.choices
        ]
        return Response(event_types, status=status.HTTP_200_OK)


class EventsListView(ListAPIView):
    """ View for listing the events """

    queryset = Event.objects.all().order_by("-status")
    serializer_class = EventSerializer
    pagination_class = CustomPageNumberPagination
    filterset_class = EventFilter


class VideoAssetDetailView(RetrieveAPIView):
    """ View for listing the VideoAsset """

    serializer_class = VideoAssetSerializer

    def get_object(self):
        obj = get_object_or_404(
            VideoAsset.objects.select_related('event__creator').prefetch_related('event__tags', 'event__playlists'),
            event_id=self.kwargs["pk"]
            )
        return obj


class TagListView(ListAPIView):
    """ View for listing all tags """

    queryset = Tag.objects.all()
    serializer_class = TagListSerializer
    pagination_class = None


class PlaylistListView(ListAPIView):
    """ View for listing all playlists """

    queryset = Playlist.objects.all()
    serializer_class = PlaylistListSerializer
    pagination_class = None


class EventRecommendationView(APIView):
    """ View for listing similar events """

    def get(self, request, event_id, *args, **kwargs):
        """ Get similar events based on the same playlist, preseneter or tags """
        event = get_object_or_404(Event, id=event_id)

        similar_events = Event.objects.filter(playlists__in=event.playlists.all()).exclude(id=event.id)

        if not similar_events.exists():
            similar_events = Event.objects.filter(
                presenters__user__in=event.presenters.values('user')
            ).exclude(id=event.id)

        if not similar_events.exists():
            similar_events = Event.objects.filter(tags__in=event.tags.all()).exclude(id=event.id)

        serializer = EventSerializer(similar_events, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
