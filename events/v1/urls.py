from django.urls import path

from events.v1.views import (
    EventRecommendationsView,
    EventsListView,
    PlaylistListView,
    TagListView,
    VideoAssetDetailView,
)

urlpatterns = [
    path('all/', EventsListView.as_view(), name='events-list'),
    path('videoasset/<int:pk>/', VideoAssetDetailView.as_view(), name='video-asset-detail'),
    path('playlists/', PlaylistListView.as_view(), name='playlist-list'),
    path('tags/', TagListView.as_view(), name='tag-list'),
    path('recommendations/<event_id>/', EventRecommendationsView.as_view(), name='recommendation')
]
