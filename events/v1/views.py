from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404

from events.models import Event, Playlist, Tag, VideoAsset
from events.v1.filters import EventFilter, PlaylistFilter, TagFilter
from events.v1.pagination import CustomPageNumberPagination
from events.v1.serializers import EventSerializer, PlaylistListSerializer, TagListSerializer, VideoAssetSerializer
from events.v1.utils import get_similar_events


class EventsListView(ListAPIView):
    """ View for listing the events """

    queryset = Event.objects.filter(videos__isnull=False)
    serializer_class = EventSerializer
    pagination_class = CustomPageNumberPagination
    filterset_class = EventFilter


class VideoAssetDetailView(RetrieveAPIView):
    """ View for listing the VideoAsset """

    serializer_class = VideoAssetSerializer

    def get_object(self):
        obj = get_object_or_404(
            VideoAsset.objects.select_related('event__creator').prefetch_related('event__tags', 'event__playlists'),
            event__slug=self.kwargs["event_slug"]
            )
        return obj


class TagListView(ListAPIView):
    """ View for listing all tags """

    queryset = Tag.objects.all()
    serializer_class = TagListSerializer
    pagination_class = None
    filterset_class = TagFilter


class PlaylistListView(ListAPIView):
    """ View for listing all playlists """

    queryset = Playlist.objects.all()
    serializer_class = PlaylistListSerializer
    pagination_class = None
    filterset_class = PlaylistFilter


class EventRecommendationsView(APIView):
    """ View for listing similar events """
    pagination_class = CustomPageNumberPagination

    def get(self, request, event_slug, *args, **kwargs):
        """ Get similar events based on the same playlist, presenter or tags """
        similar_events = get_similar_events(event_slug)

        paginator = self.pagination_class()
        paginated_events = paginator.paginate_queryset(similar_events, request, view=self)

        serializer = EventSerializer(paginated_events, many=True)
        return paginator.get_paginated_response(serializer.data)
