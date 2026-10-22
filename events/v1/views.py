from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, PolymorphicProxySerializer, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.generics import CreateAPIView, ListAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
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
    UploadChunkHeadersSerializer,
    UploadSessionCreateSerializer,
    UploadSessionSerializer,
    VideoAssetCreateSerializer,
    VideoAssetSerializer,
)
from events.v1.uploads import (
    CHUNK_CONTENT_TYPE,
    ChunkRequest,
    UploadAPIError,
    append_chunk,
    cancel_session,
    create_session,
    get_session,
    retry_finalization,
)
from events.v1.utils import get_similar_events, media_type, session_response
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

    def get_permissions(self):
        """ Listing tags is open to any authenticated user, creating one is staff only """
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsStaffPermission()]
        return super().get_permissions()


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
    """
    View for uploading a new video asset (staff only).

    A multipart body uploads the whole file in one request. A JSON body starts a resumable upload session instead, whose
    chunks are then sent to ``videoassets/<session id>/``.
    """

    permission_classes = [IsAuthenticated, IsStaffPermission]
    serializer_class = VideoAssetCreateSerializer
    parser_classes = [MultiPartParser, JSONParser]
    throttle_scope = 'upload_create'

    def get_throttles(self):
        """ Only the JSON branch that opens a resumable session is throttled """
        if media_type(self.request) == 'application/json':
            return [ScopedRateThrottle()]
        return super().get_throttles()

    @extend_schema(
        request={'multipart/form-data': VideoAssetCreateSerializer, 'application/json': UploadSessionCreateSerializer},
        responses={
            200: UploadSessionSerializer,
            201: PolymorphicProxySerializer(
                component_name='VideoAssetCreateResult',
                serializers=[VideoAssetCreateSerializer, UploadSessionSerializer],
                resource_type_field_name=None,
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        """ Multipart uploads the file at once, JSON starts a resumable session or replays the one for the same key """
        if media_type(request) != 'application/json':
            return super().post(request, *args, **kwargs)
        serializer = UploadSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session, created = create_session(request.user, serializer.validated_data)
        return session_response(session, status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@extend_schema_view(post=extend_schema(responses={201: EventSerializer}))
class EventCreateView(CreateAPIView):
    """ View for creating an event with metadata (staff only) """

    permission_classes = [IsAuthenticated, IsStaffPermission]
    serializer_class = EventCreateSerializer
    parser_classes = [MultiPartParser, JSONParser]


class UploadSessionView(APIView):
    """ Base for the staff-only resumable upload endpoints, throttled per HTTP method """

    permission_classes = [IsAuthenticated, IsStaffPermission]
    throttle_scope = None
    throttle_scopes = {}

    def get_throttles(self):
        self.throttle_scope = self.throttle_scopes.get(self.request.method)
        return [ScopedRateThrottle()] if self.throttle_scope else []


class UploadSessionDetailView(UploadSessionView):
    """ Query, append to, or cancel one upload session """

    throttle_scopes = {'GET': 'upload_status', 'PATCH': 'upload_chunk', 'DELETE': 'upload_status'}

    @extend_schema(responses={200: UploadSessionSerializer})
    def get(self, request, session_id):
        """ Authoritative upload status, including the offset to resume from """
        return session_response(get_session(session_id, request.user))

    @extend_schema(
        request={CHUNK_CONTENT_TYPE: OpenApiTypes.BINARY},
        parameters=[
            OpenApiParameter('Upload-Offset', int, OpenApiParameter.HEADER, required=True),
            OpenApiParameter('Upload-Checksum', str, OpenApiParameter.HEADER, description='sha256 <base64 digest>'),
        ],
        responses={200: UploadSessionSerializer},
    )
    def patch(self, request, session_id):
        """ Append one chunk at the committed offset. The body is streamed to disk, never buffered in memory """
        if media_type(request) != CHUNK_CONTENT_TYPE:
            raise UploadAPIError(
                'unsupported_media_type', f'Content-Type must be {CHUNK_CONTENT_TYPE}.',
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        headers = UploadChunkHeadersSerializer.from_request(request)
        headers.is_valid(raise_exception=True)
        chunk = ChunkRequest(
            offset=headers.validated_data['offset'],
            length=headers.validated_data['content_length'],
            stream=request.stream,
            checksum_sha256=headers.validated_data['checksum'],
        )
        return session_response(append_chunk(session_id, request.user, chunk))

    @extend_schema(responses={204: None})
    def delete(self, request, session_id):
        """ Cancel the upload and discard its partial file """
        cancel_session(session_id, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UploadSessionFinalizeView(UploadSessionView):
    """ Re-queue finalization of a fully uploaded file """

    throttle_scopes = {'POST': 'upload_status'}

    @extend_schema(request=None, responses={202: UploadSessionSerializer})
    def post(self, request, session_id):
        """ Idempotent: queues finalization again while it is pending, and reports a finished upload as is """
        session = retry_finalization(session_id, request.user)
        return session_response(session, status.HTTP_202_ACCEPTED)
