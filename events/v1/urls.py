from django.urls import path

from events.v1.views import (
    EventCreateView,
    EventRecommendationsView,
    EventsListView,
    PlaylistListView,
    TagListView,
    VideoAssetCreateView,
    VideoAssetDetailView,
    VideoAssetIncrementViewCountView,
)

urlpatterns = [
    path('all/', EventsListView.as_view(), name='events-list'),
    path('videoasset/<slug:event_slug>/', VideoAssetDetailView.as_view(), name='video-asset-detail'),
    path('videoasset/<slug:event_slug>/view/', VideoAssetIncrementViewCountView.as_view(), name='video-asset-increment-view'),
    path('videoassets/', VideoAssetCreateView.as_view(), name='video-asset-create'),
    path('playlists/', PlaylistListView.as_view(), name='playlist-list'),
    path('tags/', TagListView.as_view(), name='tag-list'),
    path('recommendations/<slug:event_slug>/', EventRecommendationsView.as_view(), name='recommendation'),
    path('', EventCreateView.as_view(), name='event-create'),
]
