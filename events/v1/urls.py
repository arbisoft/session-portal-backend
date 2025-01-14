from django.urls import path
from .views import EventTypeListView, EventsListView, VideoAssetListView

urlpatterns = [
    path('event_types/', EventTypeListView.as_view(), name='event-type-list'),
    path('all/', EventsListView.as_view(), name='events-list'),
    path('videoasset/<int:event_id>/', VideoAssetListView.as_view(), name='video-asset')
]
