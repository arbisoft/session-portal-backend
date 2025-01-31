from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from events.models import Event
from events.v1.filters import EventFilter
from events.v1.serializers import EventSerializer


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

    queryset = Event.objects.all()
    serializer_class = EventSerializer
    pagination_class = PageNumberPagination
    filterset_class = EventFilter
