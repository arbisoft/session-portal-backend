from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from events.models import Event

class EventTypeListView(APIView):
    def get(self, request, *args, **kwargs):
        event_types = [
            {"label": choice[0], "key": choice[1]}
            for choice in Event.EventType.choices
        ]
        return Response(event_types, status=status.HTTP_200_OK)
