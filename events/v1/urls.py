from django.urls import path

from .views import EventsListView, EventTypeListView, VideoAssetDetailView

urlpatterns = [
    path('event_types/', EventTypeListView.as_view(), name='event-type-list'),
    path('all/', EventsListView.as_view(), name='events-list'),
    path('videoasset/<int:pk>/', VideoAssetDetailView.as_view(), name='video-asset-detail')
]
