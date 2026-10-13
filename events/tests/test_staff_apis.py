from io import BytesIO
from unittest.mock import MagicMock, patch

import ffmpeg
import pytest
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from events.factories import EventFactory, PlaylistFactory, TagFactory, UserFactory, VideoAssetFactory
from events.models import Event, EventPresenter, Tag, VideoAsset
from events.v1.serializers import EventCreateSerializer


def fake_ffmpeg(duration):
    """ Build a stand-in for the ffmpeg module that probes a video of the given duration """
    def output(path, **kwargs):  # pylint: disable=unused-argument
        with open(path, 'wb') as thumbnail:
            thumbnail.write(b'thumbnail')
        return MagicMock()

    module = MagicMock()
    module.Error = ffmpeg.Error
    module.probe.return_value = {'format': {'duration': str(duration)}}
    module.input.return_value.output.side_effect = output
    return module


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


@pytest.mark.django_db
class TestVideoAssetCreateAPI:
    """ Test cases for uploading a video asset """

    @staticmethod
    def upload():
        """ Build a multipart payload with a small mp4 file """
        return {'video_file': SimpleUploadedFile('session.mp4', b'fake video content', content_type='video/mp4')}

    def test_anonymous_cannot_upload(self):
        """ Test that unauthenticated requests are rejected """
        response = APIClient().post(reverse('video-asset-create'), self.upload(), format='multipart')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not VideoAsset.objects.exists()

    def test_non_staff_cannot_upload(self, user_client):
        """ Test that regular users cannot upload videos """
        response = user_client.post(reverse('video-asset-create'), self.upload(), format='multipart')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unsupported_file_extension_is_rejected(self, staff_client):
        """ Test that a file that is not a supported video format never creates an asset """
        upload = {'video_file': SimpleUploadedFile('notes.txt', b'not a video', content_type='text/plain')}

        response = staff_client.post(reverse('video-asset-create'), upload, format='multipart')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'video_file' in response.data
        assert not VideoAsset.objects.exists()

    @pytest.mark.usefixtures('media_storage')
    def test_upload_is_marked_ready_after_processing(self, staff_client):
        """ The upload is processed synchronously, so it must not be left in PROCESSING """
        with patch('events.models.ffmpeg', fake_ffmpeg(duration=125.4)):
            response = staff_client.post(reverse('video-asset-create'), self.upload(), format='multipart')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['status'] == VideoAsset.VideoStatus.READY
        video_asset = VideoAsset.objects.get(pk=response.data['id'])
        assert video_asset.status == VideoAsset.VideoStatus.READY
        assert video_asset.duration == 125

    @pytest.mark.usefixtures('media_storage')
    def test_upload_is_marked_failed_when_probing_fails(self, staff_client):
        """ A file that ffmpeg cannot read must not be reported as ready """
        broken = fake_ffmpeg(duration=0)
        broken.probe.side_effect = ffmpeg.Error('ffprobe', b'', b'invalid data')

        with patch('events.models.ffmpeg', broken):
            response = staff_client.post(reverse('video-asset-create'), self.upload(), format='multipart')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['status'] == VideoAsset.VideoStatus.FAILED
        assert VideoAsset.objects.get(pk=response.data['id']).status == VideoAsset.VideoStatus.FAILED


@pytest.mark.django_db
class TestEventCreateAPI:
    """ Test cases for creating an event """

    @staticmethod
    def payload(video_asset_id, **extra):
        """ Build a valid event creation payload """
        data = {
            'title': 'Intro to Django',
            'description': 'A session about Django',
            'event_time': '2026-12-01T10:00:00Z',
            'video_asset_id': video_asset_id,
        }
        data.update(extra)
        return data

    @staticmethod
    def processed_video_asset():
        """ Build an unassigned video asset whose file has already been probed and thumbnailed """
        with patch('events.models.ffmpeg', fake_ffmpeg(duration=90)):
            return VideoAssetFactory(event=None, video_file=SimpleUploadedFile('session.mp4', b'fake video content'))

    @staticmethod
    def thumbnail_image():
        """ Build a valid image upload """
        buffer = BytesIO()
        Image.new('RGB', (4, 4)).save(buffer, format='PNG')
        return SimpleUploadedFile('cover.png', buffer.getvalue(), content_type='image/png')

    def test_anonymous_cannot_create_event(self):
        """ Test that unauthenticated requests are rejected """
        video_asset = VideoAssetFactory(event=None)

        response = APIClient().post(reverse('event-create'), self.payload(video_asset.id), format='json')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not Event.objects.filter(title='Intro to Django').exists()

    def test_non_staff_cannot_create_event(self, user_client):
        """ Test that regular users cannot create events """
        video_asset = VideoAssetFactory(event=None)

        response = user_client.post(reverse('event-create'), self.payload(video_asset.id), format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Event.objects.filter(title='Intro to Django').exists()

    def test_create_event_with_relations(self, staff_client):
        """ Test creating an event with presenters, tags, playlists and a video """
        video_asset = VideoAssetFactory(event=None)
        presenter = UserFactory()
        tag = TagFactory()
        playlist = PlaylistFactory()

        response = staff_client.post(
            reverse('event-create'),
            self.payload(video_asset.id, presenter_ids=[presenter.id], tags=[tag.id], playlists=[playlist.id]),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['title'] == 'Intro to Django'
        assert response.data['status'] == Event.EventStatus.PUBLISHED
        event = Event.objects.get(pk=response.data['id'])
        video_asset.refresh_from_db()
        assert video_asset.event == event
        assert list(event.tags.all()) == [tag]
        assert list(event.playlists.all()) == [playlist]
        assert list(event.presenters.all()) == [presenter]

    def test_unknown_presenter_is_rejected_without_writes(self, staff_client):
        """ A nonexistent presenter must fail validation before anything is created """
        video_asset = VideoAssetFactory(event=None)

        response = staff_client.post(
            reverse('event-create'), self.payload(video_asset.id, presenter_ids=[999999]), format='json'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'presenter_ids' in response.data
        assert not Event.objects.filter(title='Intro to Django').exists()
        assert not EventPresenter.objects.exists()
        video_asset.refresh_from_db()
        assert video_asset.event is None

    def test_unknown_video_asset_is_rejected(self, staff_client):
        """ An event must not be published without a video """
        response = staff_client.post(
            reverse('event-create'), self.payload(999999), format='json'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'video_asset_id' in response.data
        assert not Event.objects.filter(title='Intro to Django').exists()

    def test_assigned_video_asset_is_not_reassigned(self, staff_client):
        """ A video that already belongs to an event must keep it """
        original_event = EventFactory()
        video_asset = VideoAssetFactory(event=original_event)

        response = staff_client.post(reverse('event-create'), self.payload(video_asset.id), format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'video_asset_id' in response.data
        assert not Event.objects.filter(title='Intro to Django').exists()
        video_asset.refresh_from_db()
        assert video_asset.event == original_event

    @pytest.mark.parametrize('asset_status', [VideoAsset.VideoStatus.PROCESSING, VideoAsset.VideoStatus.FAILED])
    def test_unprocessed_video_asset_is_rejected(self, staff_client, asset_status):
        """ An event must not be published with a video that is not ready to play """
        video_asset = VideoAssetFactory(event=None, status=asset_status)

        response = staff_client.post(reverse('event-create'), self.payload(video_asset.id), format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'video_asset_id' in response.data
        assert not Event.objects.filter(title='Intro to Django').exists()

    def test_assigned_asset_rejected_at_lock_time(self, staff_client):
        """ The locked re-check in create() stops a request that got past validation before another one won """
        original_event = EventFactory()
        video_asset = VideoAssetFactory(event=original_event)

        with patch.object(EventCreateSerializer, 'validate_video_asset_id', side_effect=lambda value: value):
            response = staff_client.post(reverse('event-create'), self.payload(video_asset.id), format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'video_asset_id' in response.data
        assert not Event.objects.filter(title='Intro to Django').exists()
        video_asset.refresh_from_db()
        assert video_asset.event == original_event

    @pytest.mark.usefixtures('media_storage')
    def test_attach_skips_media_processing(self, staff_client):
        """ Attaching a processed video must keep its duration and thumbnail and not run ffmpeg again """
        video_asset = self.processed_video_asset()
        generated_thumbnail = video_asset.thumbnail.name

        with patch('events.models.ffmpeg') as ffmpeg_module:
            response = staff_client.post(reverse('event-create'), self.payload(video_asset.id), format='json')

        assert response.status_code == status.HTTP_201_CREATED
        ffmpeg_module.probe.assert_not_called()
        video_asset.refresh_from_db()
        assert video_asset.event_id == response.data['id']
        assert video_asset.duration == 90
        assert video_asset.thumbnail.name == generated_thumbnail

    @pytest.mark.usefixtures('media_storage')
    def test_uploaded_thumbnail_replaces_generated(self, staff_client):
        """ A thumbnail sent with the event is stored without reprocessing the video """
        video_asset = self.processed_video_asset()

        with patch('events.models.ffmpeg') as ffmpeg_module:
            response = staff_client.post(
                reverse('event-create'),
                self.payload(video_asset.id, thumbnail=self.thumbnail_image()),
                format='multipart',
            )

        assert response.status_code == status.HTTP_201_CREATED
        ffmpeg_module.probe.assert_not_called()
        video_asset.refresh_from_db()
        assert video_asset.event_id == response.data['id']
        assert video_asset.duration == 90
        assert video_asset.thumbnail.name.startswith('cover')
        assert video_asset.thumbnail.storage.exists(video_asset.thumbnail.name)

    def test_failure_after_event_creation_rolls_back(self, staff_client):
        """ A failure part way through must not leave a half-created event behind """
        video_asset = VideoAssetFactory(event=None)
        presenter = UserFactory()

        with patch('django.db.models.query.QuerySet.update', side_effect=RuntimeError('boom')):
            with pytest.raises(RuntimeError):
                staff_client.post(
                    reverse('event-create'),
                    self.payload(video_asset.id, presenter_ids=[presenter.id]),
                    format='json',
                )

        assert not Event.objects.filter(title='Intro to Django').exists()
        assert not EventPresenter.objects.exists()


@pytest.mark.django_db
class TestOpenAPISchema:
    """ Test cases for the generated OpenAPI contract """

    @pytest.fixture
    def schema(self):
        """ Returns the generated OpenAPI schema """
        response = APIClient().get(reverse('schema'), {'format': 'json'})
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_event_create_documents_full_event_response(self, schema):
        """ Test that the create endpoint documents the Event payload it actually returns """
        response_schema = schema['paths']['/api/v1/events/']['post']['responses']['201']['content']['application/json']
        assert response_schema['schema']['$ref'] == '#/components/schemas/Event'
