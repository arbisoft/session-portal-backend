from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404

from events.models import Event, Tag, VideoAsset
from events.v1.filters import EventFilter
from events.v1.pagination import CustomPageNumberPagination
from events.v1.serializers import EventSerializer, TagListSerializer, VideoAssetSerializer


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
            VideoAsset.objects.select_related('event__creator').prefetch_related('event__tags'),
            event_id=self.kwargs["pk"]
            )
        return obj


class TagListView(ListAPIView):
    """ View for listing all tags """

    queryset = Tag.objects.all()
    serializer_class = TagListSerializer
    pagination_class = None
