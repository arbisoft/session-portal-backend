import pytest
from faker import Faker
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.urls import reverse

from events.factories import EventFactory, PlaylistFactory, TagFactory, UserFactory, VideoAssetFactory
from events.models import VideoAsset

fake = Faker()
User = get_user_model()


@pytest.mark.django_db
class TestEventsAPI:
    """ Test cases for Events APIs """

    @pytest.fixture
    def api_client(self):
        """ Returns an authenticated instance of APIClient """
        client = APIClient()
        user = UserFactory()
        client.force_authenticate(user=user)
        return client

    def test_list_events(self, api_client):
        """ Test listing all events """
        EventFactory.create_batch(3)
        response = api_client.get(reverse("events-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3

    def test_video_asset_detail(self, api_client):
        """ Test retrieving a video asset detail """
        video_asset = VideoAssetFactory()
        response = api_client.get(reverse("video-asset-detail", args=[video_asset.event.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == video_asset.title
        assert response.data["status"] == VideoAsset.VideoStatus.READY

    def test_playlist_list(self, api_client):
        """ Test that only playlists linked to events are returned """
        linked_playlist = PlaylistFactory(name="Used Playlist")
        unused_playlist = PlaylistFactory(name="Unused Playlist")

        event = EventFactory()
        event.playlists.add(linked_playlist)

        response = api_client.get(reverse("playlist-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

        response = api_client.get(reverse("playlist-list"), {'linked_to_events': True})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Used Playlist"

    def test_event_tag_list(self, api_client):
        """ Test that only tags linked to events are returned """
        used_tag = TagFactory(name="Used Tag")
        unused_tag = TagFactory(name="Unused Tag")

        event = EventFactory()
        event.tags.add(used_tag)

        response = api_client.get(reverse("tag-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

        response = api_client.get(reverse("tag-list"), {'linked_to_events': True})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Used Tag"

    def test_event_recommendations(self, api_client):
        """ Test retrieving event recommendations """
        event = EventFactory()
        response = api_client.get(reverse("recommendation", args=[event.id]))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0
