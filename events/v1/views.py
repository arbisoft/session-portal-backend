from rest_framework.generics import CreateAPIView, ListAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import F, Max
from django.shortcuts import get_object_or_404

from events.models import Event, Playlist, Tag, VideoAsset
from events.v1.filters import EventFilter, PlaylistFilter, TagFilter
from events.v1.pagination import CustomPageNumberPagination
from events.v1.serializers import (
    EventCreateSerializer,
    EventSerializer,
    PlaylistListSerializer,
    TagListSerializer,
    VideoAssetCreateSerializer,
    VideoAssetSerializer,
)
from events.v1.utils import get_similar_events
from users.permissions import IsStaffPermission


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


class VideoAssetIncrementViewCountView(APIView):
    """ Increment view count for a VideoAsset by 1 """

    def post(self, request, event_slug, *args, **kwargs):
        """
        Atomically increment the view count and return the value read back after the update.

        A queryset update is used because VideoAsset.save() runs ffmpeg processing.
        """
        video_asset_id = get_object_or_404(VideoAsset.objects.values_list('pk', flat=True), event__slug=event_slug)

        queryset = VideoAsset.objects.filter(pk=video_asset_id)
        queryset.update(view_count=F('view_count') + 1)
        return Response({'view_count': queryset.values_list('view_count', flat=True).get()})


class TagListView(ListCreateAPIView):
    """ View for listing and creating tags """

    queryset = Tag.objects.annotate(
        latest_event=Max('events__event_time')
    ).order_by(F('latest_event').desc(nulls_last=True))
    serializer_class = TagListSerializer
    pagination_class = None
    filterset_class = TagFilter


class PlaylistListView(ListAPIView):
    """ View for listing all playlists """

    queryset = Playlist.objects.annotate(
        latest_event=Max('events__event_time')
    ).order_by(F('latest_event').desc(nulls_last=True))
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


class VideoAssetCreateView(CreateAPIView):
    """ View for uploading a new video asset (staff only) """

    permission_classes = [IsAuthenticated, IsStaffPermission]
    serializer_class = VideoAssetCreateSerializer
    parser_classes = [MultiPartParser]


class EventCreateView(CreateAPIView):
    """ View for creating an event with metadata (staff only) """

    permission_classes = [IsAuthenticated, IsStaffPermission]
    serializer_class = EventCreateSerializer
    parser_classes = [MultiPartParser, JSONParser]
