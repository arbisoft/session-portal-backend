from django.urls import path

from .views import EventRecommendationsView, EventsListView, EventPlaylistListView, EventTagListView, VideoAssetDetailView

urlpatterns = [
    path('all/', EventsListView.as_view(), name='events-list'),
    path('videoasset/<int:pk>/', VideoAssetDetailView.as_view(), name='video-asset-detail'),
    path('playlists/', EventPlaylistListView.as_view(), name='event-playlist-list'),
    path('tags/', EventTagListView.as_view(), name='event-tag-list'),
    path('recommendations/<event_id>/', EventRecommendationsView.as_view(), name='recommendation')
]
