from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from events.models import Event
from .serializers import EventTypeSerializer

class EventTypeListView(APIView):
    def get(self, request, *args, **kwargs):
        event_type = Event.EventType.choices
        serializer = EventTypeSerializer(event_type, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
