from django.urls import path

from events.v1.views import (
    EventRecommendationsView,
    EventsListView,
    PlaylistListView,
    TagListView,
    VideoAssetDetailView,
    VideoAssetIncrementViewCountView,
)

urlpatterns = [
    path('all/', EventsListView.as_view(), name='events-list'),
    path('videoasset/<slug:event_slug>/', VideoAssetDetailView.as_view(), name='video-asset-detail'),
    path('videoasset/<slug:event_slug>/view/', VideoAssetIncrementViewCountView.as_view(), name='video-asset-increment-view'),
    path('playlists/', PlaylistListView.as_view(), name='playlist-list'),
    path('tags/', TagListView.as_view(), name='tag-list'),
    path('recommendations/<slug:event_slug>/', EventRecommendationsView.as_view(), name='recommendation')
]
