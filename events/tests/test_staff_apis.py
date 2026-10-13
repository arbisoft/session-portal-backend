from unittest.mock import patch

import pytest
from rest_framework import status

from django.urls import reverse

from events.factories import VideoAssetFactory
from events.models import VideoAsset


@pytest.mark.django_db
class TestIncrementViewCountAPI:
    """ Test cases for the view count endpoint """

    def test_increment_skips_media_processing(self, user_client):
        """ Counting a view must not trigger the ffmpeg work done in VideoAsset.save() """
        video_asset = VideoAssetFactory()
        url = reverse('video-asset-increment-view', args=[video_asset.event.slug])

        with patch.object(VideoAsset, 'save') as save:
            response = user_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['view_count'] == 1
        save.assert_not_called()
        video_asset.refresh_from_db()
        assert video_asset.view_count == 1

    def test_unknown_event_returns_404(self, user_client):
        """ Test that an unknown event slug returns 404 """
        response = user_client.post(reverse('video-asset-increment-view', args=['missing']))

        assert response.status_code == status.HTTP_404_NOT_FOUND
