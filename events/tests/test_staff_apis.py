from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from django.urls import reverse

from events.factories import TagFactory, VideoAssetFactory
from events.models import Tag, VideoAsset


@pytest.mark.django_db
class TestTagCreateAPI:
    """ Test cases for creating tags """

    def test_anonymous_cannot_create_tag(self):
        """ Test that unauthenticated requests are rejected """
        response = APIClient().post(reverse('tag-list'), {'name': 'python'}, format='json')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not Tag.objects.filter(name='python').exists()

    def test_non_staff_cannot_create_tag(self, user_client):
        """ Tag creation is part of the staff-only publishing workflow """
        response = user_client.post(reverse('tag-list'), {'name': 'python'}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Tag.objects.filter(name='python').exists()

    def test_staff_can_create_tag(self, staff_client):
        """ Test that staff users can create a tag """
        response = staff_client.post(reverse('tag-list'), {'name': 'python'}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert Tag.objects.filter(name='python').exists()

    def test_duplicate_tag_name_is_rejected(self, staff_client):
        """ Test that a tag name that already exists returns a validation error """
        TagFactory(name='python')

        response = staff_client.post(reverse('tag-list'), {'name': 'python'}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'name' in response.data
        assert Tag.objects.filter(name='python').count() == 1

    def test_non_staff_can_still_list_tags(self, user_client):
        """ Listing stays available to any authenticated user """
        TagFactory(name='python')

        response = user_client.get(reverse('tag-list'))

        assert response.status_code == status.HTTP_200_OK
        assert [tag['name'] for tag in response.data] == ['python']


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
