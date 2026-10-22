import hashlib
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events.factories import UserFactory
from events.models import UploadSession, VideoAsset
from events.tests.test_staff_apis import fake_ffmpeg
from events.tests.test_uploads import UPLOADING, make_video, send_chunk, start_upload
from events.v1.uploads import CHUNK_CONTENT_TYPE, part_path

CLIENT_KEY = 'abcdefgh12345'
JSON_CONTENT_TYPE = 'application/json; charset=utf-8'


def multipart_upload(client):
    """ Upload a small video in a single multipart request """
    video = SimpleUploadedFile('session.mp4', make_video(64), content_type='video/mp4')
    return client.post(reverse('video-asset-create'), {'video_file': video}, format='multipart')


def chunk_upload(client, session_id):
    """ PATCH the first bytes of a session """
    return send_chunk(client, session_id, 0, make_video(100)[:50])


def cancel_upload(client, session_id):
    """ DELETE a session """
    return client.delete(reverse('upload-session-detail', args=[session_id]))


def finalize_upload(client, session_id):
    """ POST the finalize endpoint of a session """
    return client.post(reverse('upload-session-finalize', args=[session_id]))


SESSION_WRITES = {'chunk': chunk_upload, 'cancel': cancel_upload, 'finalize': finalize_upload}


@pytest.mark.django_db
@pytest.mark.usefixtures('upload_root')
class TestUploadSessionReplay:
    """ Replaying a create request with the same client key """

    def test_replay_of_lapsed_session_conflicts(self, staff_client):
        """ A key whose session ran out of time cannot be revived by replaying the create """
        first = start_upload(staff_client, make_video(100), client_key=CLIENT_KEY)
        lapsed_at = timezone.now() - timedelta(minutes=1)
        UploadSession.objects.filter(pk=first.data['id']).update(expires_at=lapsed_at)

        response = start_upload(staff_client, make_video(100), client_key=CLIENT_KEY)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'client_key_conflict'
        assert UploadSession.objects.count() == 1

    def test_client_key_with_other_checksum_conflicts(self, staff_client):
        """ Same key, name and size but a different whole-file checksum is a different upload """
        start_upload(
            staff_client, make_video(100), client_key=CLIENT_KEY, checksum_sha256=hashlib.sha256(b'a').hexdigest()
        )

        response = start_upload(
            staff_client, make_video(100), client_key=CLIENT_KEY, checksum_sha256=hashlib.sha256(b'b').hexdigest()
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'client_key_conflict'

    def test_replay_adding_checksum_conflicts(self, staff_client):
        """ A session created without a checksum cannot be claimed by a replay that supplies one """
        first = start_upload(staff_client, make_video(100), client_key=CLIENT_KEY)

        response = start_upload(
            staff_client, make_video(100), client_key=CLIENT_KEY, checksum_sha256=hashlib.sha256(b'a').hexdigest()
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'client_key_conflict'
        assert UploadSession.objects.count() == 1
        assert UploadSession.objects.get(pk=first.data['id']).checksum_sha256 == ''

    def test_replay_without_checksum_reuses_session(self, staff_client):
        """ A replay that omits the checksum returns the existing session, which keeps its checksum """
        checksum = hashlib.sha256(b'a').hexdigest()
        first = start_upload(staff_client, make_video(100), client_key=CLIENT_KEY, checksum_sha256=checksum)

        response = start_upload(staff_client, make_video(100), client_key=CLIENT_KEY)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['id'] == first.data['id']
        assert UploadSession.objects.count() == 1
        assert UploadSession.objects.get(pk=first.data['id']).checksum_sha256 == checksum

    @pytest.mark.parametrize('closed', [
        UploadSession.UploadStatus.CANCELLED, UploadSession.UploadStatus.EXPIRED, UploadSession.UploadStatus.FAILED,
    ])
    def test_replay_of_closed_session_conflicts(self, staff_client, closed):
        """ A key cannot be reused once its session was cancelled, expired or failed """
        first = start_upload(staff_client, make_video(100), client_key=CLIENT_KEY)
        UploadSession.objects.filter(pk=first.data['id']).update(status=closed)

        response = start_upload(staff_client, make_video(100), client_key=CLIENT_KEY)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'client_key_conflict'

    @pytest.mark.parametrize('open_status', [
        UploadSession.UploadStatus.FINALIZING, UploadSession.UploadStatus.COMPLETED,
    ])
    def test_replay_of_progressing_session_reused(self, staff_client, open_status):
        """ A replay after the last chunk or after completion returns the same session """
        first = start_upload(staff_client, make_video(100), client_key=CLIENT_KEY)
        UploadSession.objects.filter(pk=first.data['id']).update(status=open_status)

        response = start_upload(staff_client, make_video(100), client_key=CLIENT_KEY)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['id'] == first.data['id']


@pytest.mark.django_db
@pytest.mark.usefixtures('upload_root')
class TestUploadEntryPoints:
    """ Content types and throttling of the upload endpoints """

    @pytest.mark.usefixtures('media_storage')
    def test_multipart_post_still_creates_asset(self, staff_client):
        """ The single-request upload keeps working next to the resumable flow """
        with patch('events.models.ffmpeg', fake_ffmpeg(duration=60)):
            response = multipart_upload(staff_client)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['status'] == VideoAsset.VideoStatus.READY
        assert VideoAsset.objects.get(pk=response.data['id']).duration == 60
        assert not UploadSession.objects.exists()

    def test_json_content_type_with_charset(self, staff_client):
        """ Parameters on the Content-Type neither hide the JSON branch nor bypass its throttle """
        payload = json.dumps({'filename': 'talk.mp4', 'file_size': 100})

        with patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'upload_create': '1/min'}):
            responses = [
                staff_client.post(reverse('video-asset-create'), payload, content_type=JSON_CONTENT_TYPE)
                for _ in range(2)
            ]

        assert [response.status_code for response in responses] == [
            status.HTTP_201_CREATED, status.HTTP_429_TOO_MANY_REQUESTS
        ]
        assert responses[0].data['upload_status'] == UPLOADING
        assert UploadSession.objects.count() == 1

    @pytest.mark.usefixtures('media_storage')
    def test_throttle_applies_to_json_only(self, staff_client):
        """ Multipart uploads never consume the session-creation quota that JSON requests are held to """
        with patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'upload_create': '1/min'}):
            with patch('events.models.ffmpeg', fake_ffmpeg(duration=60)):
                multipart = [multipart_upload(staff_client).status_code for _ in range(3)]
            session_creates = [start_upload(staff_client, make_video(100)).status_code for _ in range(2)]

        assert multipart == [status.HTTP_201_CREATED] * 3
        assert session_creates == [status.HTTP_201_CREATED, status.HTTP_429_TOO_MANY_REQUESTS]

    def test_chunk_content_type_ignores_parameters(self, staff_client, session_for):
        """ A parameter after the media type does not make the chunk unsupported """
        data = make_video(100)
        session = session_for(data)

        response = staff_client.generic(
            'PATCH', reverse('upload-session-detail', args=[session.id]), data,
            content_type=f'{CHUNK_CONTENT_TYPE}; charset=binary', HTTP_UPLOAD_OFFSET='0',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['offset'] == 100


@pytest.mark.django_db
@pytest.mark.parametrize('action', SESSION_WRITES.values(), ids=list(SESSION_WRITES))
class TestUploadWriteAccess:
    """ Chunk, cancel and finalize calls from anyone but the staff owner are refused and change nothing """

    @staticmethod
    def assert_untouched(session, send_task):
        """ The session is still empty and uploading, and nothing was queued """
        session.refresh_from_db()
        assert (session.status, session.offset) == (UPLOADING, 0)
        assert not part_path(session.id).exists()
        send_task.assert_not_called()

    def test_anonymous_gets_401(self, session_for, action):
        """ Unauthenticated requests are rejected """
        session = session_for(make_video(100))

        with patch('events.v1.uploads.current_app.send_task') as send_task:
            response = action(APIClient(), session.id)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        self.assert_untouched(session, send_task)

    def test_non_staff_gets_403(self, session_for, user_client, action):
        """ Regular users have no access to the upload endpoints """
        session = session_for(make_video(100))

        with patch('events.v1.uploads.current_app.send_task') as send_task:
            response = action(user_client, session.id)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        self.assert_untouched(session, send_task)

    def test_other_staff_gets_404(self, session_for, other_staff_client, action):
        """ Another staff user cannot touch the session, nor tell that it exists """
        session = session_for(make_video(100))

        with patch('events.v1.uploads.current_app.send_task') as send_task:
            response = action(other_staff_client, session.id)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        self.assert_untouched(session, send_task)


@pytest.mark.django_db
class TestUploadSessionAdmin:
    """ Operators can inspect upload sessions in the admin but cannot change them """

    @pytest.fixture
    def superuser_client(self):
        """ A Django test client logged in as a superuser """
        client = Client()
        client.force_login(UserFactory(is_staff=True, is_superuser=True))
        return client

    def test_changelist_lists_and_searches_sessions(self, superuser_client, session_for):
        """ Sessions show up in the list and can be found by filename and by id """
        session = session_for(make_video(100), filename='keynote.mp4')
        session_for(make_video(100), filename='other.mp4')
        url = reverse('admin:events_uploadsession_changelist')

        listing = superuser_client.get(url)
        by_name = superuser_client.get(url, {'q': 'keynote'})
        by_id = superuser_client.get(url, {'q': str(session.id)})

        assert listing.status_code == status.HTTP_200_OK
        assert listing.context['cl'].result_count == 2
        assert [row.pk for row in by_name.context['cl'].result_list] == [session.pk]
        assert [row.pk for row in by_id.context['cl'].result_list] == [session.pk]

    def test_sessions_are_read_only(self, superuser_client, session_for):
        """ Adding, editing and deleting sessions is refused even for a superuser """
        session = session_for(make_video(100))
        change_url = reverse('admin:events_uploadsession_change', args=[session.pk])

        add = superuser_client.get(reverse('admin:events_uploadsession_add'))
        change = superuser_client.post(change_url, {'filename': 'renamed.mp4'})
        delete = superuser_client.post(reverse('admin:events_uploadsession_delete', args=[session.pk]), {'post': 'yes'})

        assert add.status_code == status.HTTP_403_FORBIDDEN
        assert change.status_code == status.HTTP_403_FORBIDDEN
        assert delete.status_code == status.HTTP_403_FORBIDDEN
        session.refresh_from_db()
        assert session.filename == 'talk.mp4'
        assert superuser_client.get(change_url).status_code == status.HTTP_200_OK

    def test_non_staff_cannot_open_admin(self, session_for):
        """ A user without staff status is sent to the login page """
        session_for(make_video(100))
        client = Client()
        client.force_login(UserFactory(is_staff=False))

        response = client.get(reverse('admin:events_uploadsession_changelist'))

        assert response.status_code == status.HTTP_302_FOUND
