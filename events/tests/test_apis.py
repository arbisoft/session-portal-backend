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
        events = [EventFactory() for _ in range(3)]
        for event in events:
            VideoAssetFactory(event=event)
        response = api_client.get(reverse("events-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3

    def test_list_events_with_and_without_videoasset(self, api_client):
        """ Test that /events/all returns only events with linked VideoAssets """

        # Create 2 events without video assets
        EventFactory.create_batch(2)

        # Create 3 events and attach video assets
        events_with_video = [EventFactory() for _ in range(3)]
        for event in events_with_video:
            VideoAssetFactory(event=event)

        response = api_client.get(reverse("events-list"))  # Replace with actual route name if different

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3

        returned_ids = {e["id"] for e in response.data["results"]}
        expected_ids = {e.id for e in events_with_video}

        assert returned_ids == expected_ids, "Only events with VideoAssets should be returned"

    def test_video_asset_detail(self, api_client):
        """ Test retrieving a video asset detail """
        video_asset = VideoAssetFactory()
        response = api_client.get(reverse("video-asset-detail", args=[video_asset.event.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == video_asset.title
        assert response.data["status"] == VideoAsset.VideoStatus.READY

    def test_list_playlists(self, api_client):
        """ Test listing all playlists """
        PlaylistFactory.create_batch(2)
        response = api_client.get(reverse("playlist-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

    def test_list_tags(self, api_client):
        """ Test listing all tags """
        TagFactory.create_batch(4)
        response = api_client.get(reverse("tag-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 4

    def test_event_recommendations(self, api_client):
        """ Test retrieving event recommendations """
        event = EventFactory()
        response = api_client.get(reverse("recommendation", args=[event.id]))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0
