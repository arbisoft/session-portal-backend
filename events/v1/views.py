from django.shortcuts import get_object_or_404
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework import status
from events.models import Event, VideoAsset
from events.v1.filters import EventFilter
from events.v1.serializers import EventSerializer, VideoAssetSerializer

class EventTypeListView(APIView):
    def get(self, request, *args, **kwargs):
        event_types = [
            {"label": choice[0], "key": choice[1]}
            for choice in Event.EventType.choices
        ]
        return Response(event_types, status=status.HTTP_200_OK)
    
class EventsListView(ListAPIView):

    queryset = Event.objects.all()
    serializer_class = EventSerializer
    pagination_class = PageNumberPagination
    filterset_class = EventFilter

class VideoAssetDetailView(RetrieveAPIView):
    
    serializer_class = VideoAssetSerializer
    
    def get_object(self):
        obj = get_object_or_404(
            VideoAsset.objects.select_related('event__creator').prefetch_related('event__tags'), 
            event_id=self.kwargs["pk"]
            )
        return obj