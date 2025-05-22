from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404

from events.models import Event, Playlist, Tag, VideoAsset
from events.v1.filters import EventFilter, PlaylistFilter, TagFilter
from events.v1.pagination import CustomPageNumberPagination
from events.v1.serializers import EventSerializer, PlaylistListSerializer, TagListSerializer, VideoAssetSerializer
from events.v1.utils import get_similar_events


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
    """ View for listing the tags """

    queryset = Tag.objects.all()
    serializer_class = TagListSerializer
    pagination_class = None
    filterset_class = TagFilter


class PlaylistListView(ListAPIView):
    """ View for listing the playlists """

    queryset = Playlist.objects.all()
    serializer_class = PlaylistListSerializer
    pagination_class = None
    filterset_class = PlaylistFilter


class EventRecommendationsView(APIView):
    """ View for listing similar events """

    def get(self, request, event_id, *args, **kwargs):
        """ Get similar events based on the same playlist, presenter or tags """
        similar_events = get_similar_events(event_id)
        serializer = EventSerializer(similar_events, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
