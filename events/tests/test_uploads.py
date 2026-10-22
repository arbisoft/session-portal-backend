import base64
import errno
import hashlib
import os
import threading
import time
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from kombu.exceptions import OperationalError as BrokerError
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.urls import reverse
from django.utils import timezone

from events.models import UploadSession, VideoAsset
from events.tasks import finalize_upload_session
from events.tests.test_staff_apis import fake_ffmpeg
from events.v1 import uploads
from events.v1.uploads import (
    CHUNK_CONTENT_TYPE,
    ChunkRequest,
    append_chunk,
    clean_display_filename,
    cleanup_sessions,
    confirmed_offset,
    finalize_session,
    has_valid_signature,
    part_path,
)

KIB = 1024
UPLOADING = UploadSession.UploadStatus.UPLOADING


def make_video(size):
    """ Deterministic bytes that start with a valid MP4 signature """
    header = b'\x00\x00\x00\x18ftypmp42'
    return header + bytes((index * 7) % 251 for index in range(size - len(header)))


def sha256_header(body):
    """ Upload-Checksum header value for a chunk """
    return 'sha256 ' + base64.b64encode(hashlib.sha256(body).digest()).decode()


def start_upload(client, data, **overrides):
    """ Create a session for ``data`` and return the response """
    payload = {'filename': 'talk.mp4', 'file_size': len(data), **overrides}
    return client.post(reverse('video-asset-create'), payload, format='json')


def send_chunk(client, session_id, offset, body, **extra):
    """ PATCH one chunk the way the frontend does """
    return client.generic(
        'PATCH', reverse('upload-session-detail', args=[session_id]), body,
        content_type=CHUNK_CONTENT_TYPE, HTTP_UPLOAD_OFFSET=str(offset), **extra,
    )


def send_truncated_chunk(client, session_id, offset, body, declared_length):
    """ PATCH a chunk whose body ends early, like a connection that dropped after ``len(body)`` bytes """
    return send_chunk(
        client, session_id, offset, body, CONTENT_LENGTH=str(declared_length), **{'wsgi.input': BytesIO(body)}
    )


def upload_in_chunks(client, session_id, data, chunk_size):
    """ Send ``data`` in consecutive chunks and return the last response """
    response = None
    for offset in range(0, len(data), chunk_size):
        response = send_chunk(client, session_id, offset, data[offset:offset + chunk_size])
        assert response.status_code == status.HTTP_200_OK
    return response


def broken_stream(data):
    """ Request body that delivers ``data`` and then fails like a dropped connection """
    stream = MagicMock()
    stream.read.side_effect = [data, OSError('connection reset')]
    return stream


def request_from(data, offset=0, **kwargs):
    """ Build a ChunkRequest backed by an in-memory stream """
    return ChunkRequest(offset=offset, length=len(data), stream=BytesIO(data), **kwargs)


@pytest.mark.django_db
@pytest.mark.usefixtures('upload_root')
class TestUploadSessionCreation:
    """ Creating upload sessions """

    def test_anonymous_cannot_create_session(self):
        """ Unauthenticated requests are rejected """
        response = APIClient().post(reverse('video-asset-create'), {}, format='json')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_staff_cannot_create_session(self, user_client):
        """ Uploading is part of the staff-only publishing workflow """
        response = start_upload(user_client, b'x' * 10)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not UploadSession.objects.exists()

    def test_create_session_starts_at_offset_zero(self, staff_client, settings):
        """ A new session reports its limits and nothing uploaded yet """
        response = start_upload(staff_client, make_video(100))

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['offset'] == 0
        assert response.data['upload_status'] == UPLOADING
        assert response.data['chunk_size'] == settings.RESUMABLE_UPLOAD_CHUNK_BYTES
        assert response.data['max_chunk_size'] == settings.RESUMABLE_UPLOAD_MAX_CHUNK_BYTES
        assert response['Upload-Offset'] == '0'
        assert UploadSession.objects.get(pk=response.data['id']).owner.is_staff

    def test_unsupported_extension_is_rejected(self, staff_client):
        """ Only the video extensions the asset model accepts may be uploaded """
        response = start_upload(staff_client, b'x' * 10, filename='malware.exe')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'filename' in response.data

    def test_oversized_file_is_rejected(self, staff_client, settings):
        """ The declared size is checked against the configured limit up front """
        settings.RESUMABLE_UPLOAD_MAX_FILE_BYTES = 50

        response = start_upload(staff_client, b'x' * 51)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'file_size' in response.data

    def test_path_in_filename_is_discarded(self, staff_client, upload_root):
        """ Directories in the client-supplied name never reach storage """
        response = start_upload(staff_client, make_video(100), filename='../../etc/pass wd.mp4')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['filename'] == 'pass wd.mp4'
        assert not any(upload_root.parent.glob('**/etc'))

    def test_malformed_checksum_is_rejected(self, staff_client):
        """ The optional whole-file checksum must be a SHA-256 hex digest """
        response = start_upload(staff_client, make_video(100), checksum_sha256='nope')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_replayed_client_key_returns_same_session(self, staff_client):
        """ Retrying an ambiguous create does not leave a second session behind """
        first = start_upload(staff_client, make_video(100), client_key='abcdefgh12345')
        second = start_upload(staff_client, make_video(100), client_key='abcdefgh12345')

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_200_OK
        assert second.data['id'] == first.data['id']
        assert UploadSession.objects.count() == 1

    def test_client_key_for_other_file_conflicts(self, staff_client):
        """ A key cannot be recycled for a different file """
        start_upload(staff_client, make_video(100), client_key='abcdefgh12345')

        response = start_upload(staff_client, make_video(200), client_key='abcdefgh12345')

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'client_key_conflict'

    def test_active_upload_limit_is_enforced(self, staff_client, settings):
        """ A user can only keep a few uploads in flight """
        settings.RESUMABLE_UPLOAD_MAX_ACTIVE_PER_USER = 1
        start_upload(staff_client, make_video(100))

        response = start_upload(staff_client, make_video(100))

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'too_many_active_uploads'

    def test_insufficient_disk_space_is_reported(self, staff_client):
        """ Creation fails fast when the volume cannot hold the file """
        with patch('events.v1.uploads.shutil.disk_usage') as disk_usage:
            disk_usage.return_value.free = 10
            response = start_upload(staff_client, make_video(100))

        assert response.status_code == status.HTTP_507_INSUFFICIENT_STORAGE
        assert response.data['code'] == 'insufficient_storage'

    def test_space_reserved_by_other_uploads_counts(self, staff_client, session_for, settings):
        """ Disk already promised to unfinished uploads is not offered again """
        session_for(make_video(1000))
        settings.RESUMABLE_UPLOAD_MIN_FREE_BYTES = 0

        with patch('events.v1.uploads.shutil.disk_usage') as disk_usage:
            disk_usage.return_value.free = 1500
            response = start_upload(staff_client, make_video(600))

        assert response.status_code == status.HTTP_507_INSUFFICIENT_STORAGE

    def test_session_creation_is_rate_limited(self, staff_client):
        """ Session creation is throttled per user """
        with patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'upload_create': '2/min'}):
            codes = [start_upload(staff_client, make_video(100)).status_code for _ in range(3)]

        assert codes == [status.HTTP_201_CREATED, status.HTTP_201_CREATED, status.HTTP_429_TOO_MANY_REQUESTS]


@pytest.mark.django_db
class TestUploadChunks:
    """ Appending chunks, offsets and idempotency """

    def test_chunk_advances_committed_offset(self, staff_client, session_for):
        """ A chunk at the committed offset is persisted and acknowledged """
        data = make_video(300)
        session = session_for(data)

        response = send_chunk(staff_client, session.id, 0, data[:100])

        assert response.status_code == status.HTTP_200_OK
        assert response.data['offset'] == 100
        assert response['Upload-Offset'] == '100'
        session.refresh_from_db()
        assert session.offset == 100
        assert part_path(session.id).read_bytes() == data[:100]

    def test_last_chunk_moves_session_to_finalizing(self, staff_client, session_for):
        """ Completing the byte range hands the session to finalization, not straight to completed """
        data = make_video(300)
        session = session_for(data)

        response = upload_in_chunks(staff_client, session.id, data, 100)

        assert response.data['upload_status'] == UploadSession.UploadStatus.FINALIZING
        assert response.data['offset'] == 300

    def test_last_chunk_queues_finalization(self, staff_client, session_for, django_capture_on_commit_callbacks):
        """ The finalize task is only queued once the commit is durable """
        data = make_video(200)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])

        with patch('events.v1.uploads.current_app.send_task') as send_task:
            with django_capture_on_commit_callbacks(execute=True):
                send_chunk(staff_client, session.id, 100, data[100:])

        send_task.assert_called_once_with('events.tasks.finalize_upload_session', args=[str(session.id)])

    def test_wrong_offset_reports_server_offset(self, staff_client, session_for):
        """ The client is told where to resume instead of corrupting the file """
        data = make_video(300)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])

        response = send_chunk(staff_client, session.id, 200, data[200:])

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'offset_mismatch'
        assert response.data['offset'] == 100
        assert part_path(session.id).read_bytes() == data[:100]

    def test_retried_chunk_is_not_appended_twice(self, staff_client, session_for):
        """ Replaying a chunk whose ack was lost is rejected without touching the file """
        data = make_video(300)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])

        replay = send_chunk(staff_client, session.id, 0, data[:100])

        assert replay.status_code == status.HTTP_409_CONFLICT
        assert replay.data['offset'] == 100
        assert part_path(session.id).stat().st_size == 100

    def test_chunk_past_declared_size_is_rejected(self, staff_client, session_for):
        """ Writes cannot exceed the size agreed at creation """
        data = make_video(100)
        session = session_for(data)

        response = send_chunk(staff_client, session.id, 0, data + b'extra')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['code'] == 'chunk_out_of_range'

    def test_oversized_chunk_is_rejected(self, staff_client, session_for, settings):
        """ The per-request cap bounds memory, disk and proxy limits """
        settings.RESUMABLE_UPLOAD_MAX_CHUNK_BYTES = 50
        data = make_video(300)
        session = session_for(data)

        response = send_chunk(staff_client, session.id, 0, data[:100])

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert response.data['code'] == 'chunk_too_large'
        assert not part_path(session.id).exists()

    def test_wrong_content_type_is_rejected(self, staff_client, session_for):
        """ Only the offset octet-stream media type is accepted """
        data = make_video(100)
        session = session_for(data)

        response = staff_client.generic(
            'PATCH', reverse('upload-session-detail', args=[session.id]), data,
            content_type='application/json', HTTP_UPLOAD_OFFSET='0',
        )

        assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    def test_missing_offset_header_is_rejected(self, staff_client, session_for):
        """ The offset is mandatory """
        data = make_video(100)
        session = session_for(data)

        response = staff_client.generic(
            'PATCH', reverse('upload-session-detail', args=[session.id]), data, content_type=CHUNK_CONTENT_TYPE
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'offset' in response.data

    def test_matching_chunk_checksum_is_accepted(self, staff_client, session_for):
        """ A correct Upload-Checksum passes """
        data = make_video(100)
        session = session_for(data)

        response = send_chunk(staff_client, session.id, 0, data, HTTP_UPLOAD_CHECKSUM=sha256_header(data))

        assert response.status_code == status.HTTP_200_OK

    def test_checksum_mismatch_commits_nothing(self, staff_client, session_for):
        """ Corrupted bytes are discarded and the offset stays put """
        data = make_video(100)
        session = session_for(data)

        response = send_chunk(staff_client, session.id, 0, data, HTTP_UPLOAD_CHECKSUM=sha256_header(b'other'))

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.data['code'] == 'checksum_mismatch'
        session.refresh_from_db()
        assert session.offset == 0
        assert part_path(session.id).stat().st_size == 0

    def test_malformed_checksum_header_is_rejected(self, staff_client, session_for):
        """ Unknown algorithms and bad base64 are a client error """
        data = make_video(100)
        session = session_for(data)

        response = send_chunk(staff_client, session.id, 0, data, HTTP_UPLOAD_CHECKSUM='md5 AAAA')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_wrong_file_signature_fails_fast(self, staff_client, session_for):
        """ A file that is not a video is refused on its first chunk, not after the whole upload """
        data = b'This is plain text pretending to be a video file.' * 3
        session = session_for(data)

        response = send_chunk(staff_client, session.id, 0, data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.data['code'] == 'invalid_file_signature'
        session.refresh_from_db()
        assert session.offset == 0

    def test_chunk_request_is_throttled(self, staff_client, session_for):
        """ Chunk writes are rate limited as well """
        data = make_video(300)
        session = session_for(data)

        with patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'upload_chunk': '1/min'}):
            first = send_chunk(staff_client, session.id, 0, data[:100])
            second = send_chunk(staff_client, session.id, 100, data[100:200])

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
class TestUploadRecovery:
    """ Interrupted, ambiguous and concurrent writes """

    def test_dropped_connection_commits_nothing(self, staff_client, session_for):
        """ A chunk that is cut short leaves the committed offset and the file untouched """
        data = make_video(300)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])

        response = send_truncated_chunk(staff_client, session.id, 100, data[100:200], 150)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['code'] == 'incomplete_chunk'
        session.refresh_from_db()
        assert session.offset == 100
        assert part_path(session.id).read_bytes() == data[:100]

    def test_broken_stream_is_rolled_back(self, session_for):
        """ A read error mid-chunk truncates the partial bytes that were already written """
        data = make_video(300)
        session = session_for(data)

        with pytest.raises(uploads.UploadAPIError) as error:
            append_chunk(session.id, session.owner, ChunkRequest(0, 200, broken_stream(data[:100])))

        assert error.value.detail['code'] == 'incomplete_chunk'
        assert part_path(session.id).stat().st_size == 0

    def test_resume_after_interruption_rebuilds_file(self, staff_client, session_for):
        """ Disconnect mid-upload, ask the server where it is, send only the rest, get identical bytes """
        data = make_video(1000)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:400])
        broken = send_truncated_chunk(staff_client, session.id, 400, data[400:550], 300)

        resume_from = staff_client.get(reverse('upload-session-detail', args=[session.id])).data['offset']
        for offset in range(resume_from, len(data), 300):
            final = send_chunk(staff_client, session.id, offset, data[offset:offset + 300])

        assert broken.status_code == status.HTTP_400_BAD_REQUEST
        assert resume_from == 400
        assert final.data['upload_status'] == UploadSession.UploadStatus.FINALIZING
        assert part_path(session.id).read_bytes() == data

    def test_stale_bytes_after_crash_are_discarded(self, staff_client, session_for):
        """ Bytes written but never committed (crash before the DB update) are overwritten by the next chunk """
        data = make_video(300)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])
        with open(part_path(session.id), 'ab') as handle:
            handle.write(b'uncommitted-garbage' * 20)

        response = send_chunk(staff_client, session.id, 100, data[100:200])

        assert response.status_code == status.HTTP_200_OK
        assert part_path(session.id).read_bytes() == data[:200]

    def test_database_failure_after_write_is_recoverable(self, staff_client, session_for):
        """ If the offset commit fails after the bytes were fsynced, a retry still produces a correct file """
        data = make_video(300)
        session = session_for(data)

        with patch.object(UploadSession, 'save', side_effect=DatabaseError('db down')):
            with pytest.raises(DatabaseError):
                append_chunk(session.id, session.owner, request_from(data[:100]))
        retry = send_chunk(staff_client, session.id, 0, data[:100])

        assert retry.status_code == status.HTTP_200_OK
        assert part_path(session.id).read_bytes() == data[:100]

    def test_lost_partial_file_lowers_offset(self, staff_client, session_for):
        """ Committed metadata is never trusted over the disk: lost bytes reset the resume position """
        data = make_video(300)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])
        part_path(session.id).unlink()

        status_response = staff_client.get(reverse('upload-session-detail', args=[session.id]))
        stale = send_chunk(staff_client, session.id, 100, data[100:200])

        assert status_response.data['offset'] == 0
        assert stale.status_code == status.HTTP_409_CONFLICT
        assert stale.data['offset'] == 0
        session.refresh_from_db()
        assert session.offset == 0
        assert confirmed_offset(session) == 0

    def test_storage_full_returns_507_and_rolls_back(self, staff_client, session_for):
        """ Running out of disk mid-chunk is reported and leaves the committed state intact """
        data = make_video(300)
        session = session_for(data)

        with patch('events.v1.uploads.os.fsync', side_effect=OSError(errno.ENOSPC, 'No space left')):
            response = send_chunk(staff_client, session.id, 0, data[:100])

        assert response.status_code == status.HTTP_507_INSUFFICIENT_STORAGE
        session.refresh_from_db()
        assert session.offset == 0
        assert part_path(session.id).stat().st_size == 0

    def test_expired_session_rejects_chunks(self, staff_client, session_for):
        """ Past its expiry a session takes no more data """
        data = make_video(300)
        session = session_for(data)
        UploadSession.objects.filter(pk=session.pk).update(expires_at=timezone.now() - timedelta(minutes=1))

        response = send_chunk(staff_client, session.id, 0, data[:100])

        assert response.status_code == status.HTTP_410_GONE
        assert response.data['code'] == 'session_expired'

    def test_successful_chunk_extends_expiry(self, staff_client, session_for):
        """ Activity keeps a session alive """
        data = make_video(300)
        session = session_for(data)
        soon = timezone.now() + timedelta(minutes=5)
        UploadSession.objects.filter(pk=session.pk).update(expires_at=soon)

        send_chunk(staff_client, session.id, 0, data[:100])

        session.refresh_from_db()
        assert session.expires_at > soon + timedelta(hours=1)

    def test_finalizing_session_rejects_chunks(self, staff_client, session_for):
        """ Nothing can be appended once the whole file has been received """
        data = make_video(100)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data)

        response = send_chunk(staff_client, session.id, 100, b'x')

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'session_not_active'

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_writer_gets_conflict(self, session_for):
        """ While one request holds the session lock, a second writer is turned away instead of interleaving """
        data = make_video(300)
        session = session_for(data)
        locked, release = threading.Event(), threading.Event()

        def hold_lock():
            try:
                with transaction.atomic():
                    UploadSession.objects.select_for_update().get(pk=session.pk)
                    locked.set()
                    release.wait(10)
            finally:
                connection.close()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        assert locked.wait(10)
        try:
            with pytest.raises(uploads.UploadAPIError) as error:
                append_chunk(session.id, session.owner, request_from(data[:100]))
        finally:
            release.set()
            holder.join()

        assert error.value.detail['code'] == 'upload_in_progress'
        assert error.value.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
class TestUploadStatusAndCancel:
    """ Status queries, ownership and cancellation """

    def test_status_reports_confirmed_offset(self, staff_client, session_for):
        """ The status endpoint is the source of truth for resuming """
        data = make_video(300)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])

        response = staff_client.get(reverse('upload-session-detail', args=[session.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['offset'] == 100
        assert response['Upload-Offset'] == '100'
        assert response['Cache-Control'] == 'no-store'

    def test_other_users_session_looks_missing(self, staff_client, session_for, other_staff_client):
        """ Another user cannot read, write to or cancel a session, nor tell that it exists """
        data = make_video(300)
        session = session_for(data)
        url = reverse('upload-session-detail', args=[session.id])

        assert other_staff_client.get(url).status_code == status.HTTP_404_NOT_FOUND
        assert send_chunk(other_staff_client, session.id, 0, data[:100]).status_code == status.HTTP_404_NOT_FOUND
        assert other_staff_client.delete(url).status_code == status.HTTP_404_NOT_FOUND
        finalize_url = reverse('upload-session-finalize', args=[session.id])
        assert other_staff_client.post(finalize_url).status_code == status.HTTP_404_NOT_FOUND
        assert staff_client.get(url).status_code == status.HTTP_200_OK

    def test_non_staff_cannot_read_status(self, session_for, user_client):
        """ Regular users have no access to the upload endpoints """
        session = session_for(make_video(100))

        response = user_client.get(reverse('upload-session-detail', args=[session.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.usefixtures('upload_root')
    def test_unknown_session_is_not_found(self, staff_client):
        """ Unknown identifiers return 404 """
        response = staff_client.get(reverse('upload-session-detail', args=['3f2b8c9e-1b0a-4c75-9d56-0d4c4f2d1e11']))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cancel_discards_partial_file(self, staff_client, session_for, django_capture_on_commit_callbacks):
        """ Cancelling frees the disk and closes the session for further writes """
        data = make_video(300)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])
        url = reverse('upload-session-detail', args=[session.id])

        with django_capture_on_commit_callbacks(execute=True):
            response = staff_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        session.refresh_from_db()
        assert session.status == UploadSession.UploadStatus.CANCELLED
        assert not part_path(session.id).exists()
        assert send_chunk(staff_client, session.id, 100, data[100:200]).status_code == status.HTTP_410_GONE

    def test_cancel_twice_is_harmless(self, staff_client, session_for):
        """ DELETE is idempotent """
        session = session_for(make_video(100))
        url = reverse('upload-session-detail', args=[session.id])

        assert staff_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
        assert staff_client.delete(url).status_code == status.HTTP_204_NO_CONTENT

    def test_cancelling_a_failed_upload_is_a_no_op(self, staff_client, session_for):
        """ A session that already failed has nothing left to cancel, so the call succeeds instead of conflicting """
        session = session_for(make_video(100))
        UploadSession.objects.filter(pk=session.pk).update(status=UploadSession.UploadStatus.FAILED)

        response = staff_client.delete(reverse('upload-session-detail', args=[session.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        session.refresh_from_db()
        assert session.status == UploadSession.UploadStatus.FAILED

    def test_cannot_cancel_finalizing_upload(self, staff_client, session_for):
        """ Once every byte is in, the upload can no longer be cancelled """
        data = make_video(100)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data)

        response = staff_client.delete(reverse('upload-session-detail', args=[session.id]))

        assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
class TestUploadFinalization:
    """ Promotion of a fully uploaded file to a VideoAsset """

    @pytest.fixture(autouse=True)
    def storage(self, media_storage, upload_root):  # pylint: disable=unused-argument
        """ Keep promoted videos and partial files in temporary directories """

    def finished_session(self, staff_client, session_for, data, **overrides):
        """ A session whose bytes have all been uploaded """
        session = session_for(data, **overrides)
        upload_in_chunks(staff_client, session.id, data, 128)
        session.refresh_from_db()
        return session

    def test_finalize_creates_ready_asset_with_same_bytes(self, staff_client, session_for, media_storage):
        """ End to end: the stored video is byte-for-byte the uploaded file """
        data = make_video(1000)
        session = self.finished_session(staff_client, session_for, data)

        with patch('events.models.ffmpeg', fake_ffmpeg(90)):
            result = finalize_session(session.id)

        assert result.status == UploadSession.UploadStatus.COMPLETED
        asset = VideoAsset.objects.get(pk=result.video_asset_id)
        assert asset.status == VideoAsset.VideoStatus.READY
        assert asset.title == 'talk'
        assert (media_storage / 'video_file' / f'{session.id}.mp4').read_bytes() == data
        assert not part_path(session.id).exists()

    def test_status_endpoint_exposes_video_asset(self, staff_client, session_for):
        """ The client learns the asset id from the completed session """
        session = self.finished_session(staff_client, session_for, make_video(500))
        with patch('events.models.ffmpeg', fake_ffmpeg(90)):
            finalize_session(session.id)

        response = staff_client.get(reverse('upload-session-detail', args=[session.id]))

        assert response.data['upload_status'] == UploadSession.UploadStatus.COMPLETED
        assert response.data['video_asset_id'] == VideoAsset.objects.get().pk

    def test_finalize_is_idempotent(self, staff_client, session_for):
        """ Running finalization again creates no second asset """
        session = self.finished_session(staff_client, session_for, make_video(500))

        with patch('events.models.ffmpeg', fake_ffmpeg(90)):
            finalize_session(session.id)
            finalize_session(session.id)

        assert VideoAsset.objects.count() == 1

    def test_finalize_resumes_after_crash_following_move(self, staff_client, session_for, media_storage):
        """ A worker that died after promoting the file but before the commit is picked up by the retry """
        data = make_video(500)
        session = self.finished_session(staff_client, session_for, data)
        destination = media_storage / 'video_file' / f'{session.id}.mp4'
        destination.parent.mkdir(parents=True, exist_ok=True)
        part_path(session.id).rename(destination)

        with patch('events.models.ffmpeg', fake_ffmpeg(90)):
            result = finalize_session(session.id)

        assert result.status == UploadSession.UploadStatus.COMPLETED
        assert destination.read_bytes() == data

    def test_finalize_detects_truncated_file(self, staff_client, session_for):
        """ A file that lost bytes since the last chunk fails verification rather than being published """
        session = self.finished_session(staff_client, session_for, make_video(500))
        with open(part_path(session.id), 'r+b') as handle:
            handle.truncate(400)

        result = finalize_session(session.id)

        assert result.status == UploadSession.UploadStatus.FAILED
        assert result.error_code == 'size_mismatch'
        assert not VideoAsset.objects.exists()

    def test_whole_file_checksum_is_verified(self, staff_client, session_for):
        """ A mismatching whole-file checksum fails the session """
        session = self.finished_session(
            staff_client, session_for, make_video(500), checksum_sha256=hashlib.sha256(b'other').hexdigest()
        )

        result = finalize_session(session.id)

        assert result.status == UploadSession.UploadStatus.FAILED
        assert result.error_code == 'checksum_mismatch'
        assert not part_path(session.id).exists()

    def test_matching_whole_file_checksum_passes(self, staff_client, session_for):
        """ A correct whole-file checksum lets the upload complete """
        data = make_video(500)
        session = self.finished_session(
            staff_client, session_for, data, checksum_sha256=hashlib.sha256(data).hexdigest().upper()
        )

        with patch('events.models.ffmpeg', fake_ffmpeg(90)):
            result = finalize_session(session.id)

        assert result.status == UploadSession.UploadStatus.COMPLETED

    def test_unprocessable_video_fails_session(self, staff_client, session_for):
        """ When ffmpeg finds no duration the asset is FAILED and the session reports it """
        session = self.finished_session(staff_client, session_for, make_video(500))

        with patch('events.models.ffmpeg', fake_ffmpeg(0)):
            result = finalize_session(session.id)

        assert result.status == UploadSession.UploadStatus.FAILED
        assert result.error_code == 'processing_failed'
        assert VideoAsset.objects.get().status == VideoAsset.VideoStatus.FAILED

    def test_finalize_ignores_sessions_still_uploading(self, session_for):
        """ Finalization only acts on sessions whose bytes are all in """
        session = session_for(make_video(500))

        result = finalize_session(session.id)

        assert result.status == UPLOADING
        assert not VideoAsset.objects.exists()

    def test_finalize_unknown_session_returns_none(self):
        """ A task for a purged session is a no-op """
        assert finalize_session('3f2b8c9e-1b0a-4c75-9d56-0d4c4f2d1e11') is None

    def test_celery_task_runs_finalization(self, staff_client, session_for):
        """ The registered task drives the same code path """
        session = self.finished_session(staff_client, session_for, make_video(500))

        with patch('events.models.ffmpeg', fake_ffmpeg(90)):
            outcome = finalize_upload_session.apply(args=[str(session.id)]).get()

        assert outcome == UploadSession.UploadStatus.COMPLETED

    def test_finalize_endpoint_requeues_pending_session(self, staff_client, session_for):
        """ The client can nudge a session whose task was lost """
        session = self.finished_session(staff_client, session_for, make_video(500))

        with patch('events.v1.uploads.current_app.send_task') as send_task:
            response = staff_client.post(reverse('upload-session-finalize', args=[session.id]))

        assert response.status_code == status.HTTP_202_ACCEPTED
        send_task.assert_called_once()

    def test_finalize_endpoint_leaves_completed_alone(self, staff_client, session_for):
        """ Repeating the call after completion queues nothing """
        session = self.finished_session(staff_client, session_for, make_video(500))
        with patch('events.models.ffmpeg', fake_ffmpeg(90)):
            finalize_session(session.id)

        with patch('events.v1.uploads.current_app.send_task') as send_task:
            response = staff_client.post(reverse('upload-session-finalize', args=[session.id]))

        assert response.status_code == status.HTTP_202_ACCEPTED
        send_task.assert_not_called()

    def test_finalize_endpoint_rejects_unfinished_upload(self, staff_client, session_for):
        """ A session still receiving data cannot be finalized """
        session = session_for(make_video(500))

        response = staff_client.post(reverse('upload-session-finalize', args=[session.id]))

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_finalize_endpoint_reports_queue_outage(self, staff_client, session_for):
        """ When the task cannot be queued the client is told to retry, not given a false 202 """
        session = self.finished_session(staff_client, session_for, make_video(500))

        with patch('events.v1.uploads.current_app.send_task', side_effect=BrokerError('down')):
            response = staff_client.post(reverse('upload-session-finalize', args=[session.id]))

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.data['code'] == 'queue_unavailable'
        session.refresh_from_db()
        assert session.status == UploadSession.UploadStatus.FINALIZING

    def test_broker_outage_does_not_fail_the_chunk(self, staff_client, session_for, django_capture_on_commit_callbacks):
        """ If the task cannot be queued the upload still succeeds and the sweep recovers it later """
        data = make_video(100)
        session = session_for(data)

        with patch('events.v1.uploads.current_app.send_task', side_effect=BrokerError('down')):
            with django_capture_on_commit_callbacks(execute=True):
                response = send_chunk(staff_client, session.id, 0, data)

        assert response.status_code == status.HTTP_200_OK
        session.refresh_from_db()
        assert session.status == UploadSession.UploadStatus.FINALIZING


@pytest.mark.django_db
class TestUploadCleanup:
    """ Expiry, retention and orphan handling """

    @pytest.fixture(autouse=True)
    def storage(self, upload_root):  # pylint: disable=unused-argument
        """ Keep partial files in a temporary directory """

    def test_abandoned_sessions_expire(self, staff_client, session_for, django_capture_on_commit_callbacks):
        """ Expired sessions are closed and their partial files removed """
        data = make_video(300)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])
        UploadSession.objects.filter(pk=session.pk).update(expires_at=timezone.now() - timedelta(hours=1))

        with django_capture_on_commit_callbacks(execute=True):
            summary = cleanup_sessions()

        session.refresh_from_db()
        assert summary['expired'] == 1
        assert session.status == UploadSession.UploadStatus.EXPIRED
        assert not part_path(session.id).exists()

    def test_live_sessions_are_kept(self, staff_client, session_for):
        """ Sessions within their lifetime are untouched """
        data = make_video(300)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data[:100])

        summary = cleanup_sessions()

        session.refresh_from_db()
        assert summary['expired'] == 0
        assert session.status == UPLOADING
        assert part_path(session.id).exists()

    def test_old_terminal_sessions_are_purged(self, session_for, settings):
        """ Closed sessions disappear after the retention period """
        session = session_for(make_video(100))
        UploadSession.objects.filter(pk=session.pk).update(status=UploadSession.UploadStatus.CANCELLED)
        past = timezone.now() - timedelta(days=settings.RESUMABLE_UPLOAD_RETENTION_DAYS + 1)
        UploadSession.objects.filter(pk=session.pk).update(modified=past)

        summary = cleanup_sessions()

        assert summary['purged'] == 1
        assert not UploadSession.objects.exists()

    def test_recent_terminal_sessions_are_retained(self, session_for):
        """ Recently closed sessions stay for diagnosis """
        session = session_for(make_video(100))
        UploadSession.objects.filter(pk=session.pk).update(status=UploadSession.UploadStatus.CANCELLED)

        assert cleanup_sessions()['purged'] == 0
        assert UploadSession.objects.filter(pk=session.pk).exists()

    def test_orphaned_partial_files_are_swept(self, session_for, upload_root):
        """ Old partial files with no active session are deleted, fresh ones are left alone """
        active = session_for(make_video(100))
        send_chunk_path = part_path(active.id)
        send_chunk_path.write_bytes(b'x')
        old_orphan = upload_root / '3f2b8c9e-1b0a-4c75-9d56-0d4c4f2d1e11.part'
        new_orphan = upload_root / '4f2b8c9e-1b0a-4c75-9d56-0d4c4f2d1e11.part'
        old_orphan.write_bytes(b'x')
        new_orphan.write_bytes(b'x')
        ancient = time.time() - 7200
        for path in (old_orphan, send_chunk_path):
            os.utime(path, (ancient, ancient))

        summary = cleanup_sessions()

        assert summary['orphan_files_removed'] == 1
        assert not old_orphan.exists()
        assert new_orphan.exists()
        assert send_chunk_path.exists()

    def test_vanishing_orphan_does_not_abort_sweep(self, upload_root):
        """ A partial file that disappears between listing and stat is skipped, the rest are still removed """
        vanishing = upload_root / '3f2b8c9e-1b0a-4c75-9d56-0d4c4f2d1e11.part'
        stale = upload_root / '4f2b8c9e-1b0a-4c75-9d56-0d4c4f2d1e11.part'
        upload_root.mkdir(parents=True, exist_ok=True)
        ancient = time.time() - 7200
        for path in (vanishing, stale):
            path.write_bytes(b'x')
            os.utime(path, (ancient, ancient))
        real_stat = Path.stat

        def stat_after_removal(path, *args, **kwargs):
            if path.name == vanishing.name:
                raise FileNotFoundError(errno.ENOENT, 'gone', str(path))
            return real_stat(path, *args, **kwargs)

        with patch.object(Path, 'stat', stat_after_removal):
            summary = cleanup_sessions()

        assert summary['orphan_files_removed'] == 1
        assert not stale.exists()

    def test_stalled_finalization_is_requeued(self, staff_client, session_for, settings):
        """ A FINALIZING session whose task vanished is queued again """
        data = make_video(100)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data)
        stale = timezone.now() - timedelta(minutes=settings.RESUMABLE_UPLOAD_FINALIZE_STALE_MINUTES + 1)
        UploadSession.objects.filter(pk=session.pk).update(modified=stale)

        with patch('events.v1.uploads.current_app.send_task') as send_task:
            summary = cleanup_sessions()

        assert summary['finalizations_redispatched'] == 1
        send_task.assert_called_once()

    def test_management_command_reports_summary(self, capsys):
        """ The command is a thin wrapper that prints the cleanup summary """
        call_command('cleanup_upload_sessions')

        assert 'expired: 0' in capsys.readouterr().out


class TestUploadHelpers:
    """ Pure helpers """

    @pytest.mark.parametrize('raw,expected', [
        ('talk.mp4', 'talk.mp4'),
        ('../../etc/passwd.mp4', 'passwd.mp4'),
        ('C:\\Users\\me\\talk.mov', 'talk.mov'),
        ('bad\x00name\n.webm', 'badname.webm'),
        ('..', ''),
    ])
    def test_display_filename_is_cleaned(self, raw, expected):
        """ Paths and control characters never survive """
        assert clean_display_filename(raw) == expected

    @pytest.mark.parametrize('header,extension,valid', [
        (b'\x00\x00\x00\x18ftypmp42', 'mp4', True),
        (b'\x00\x00\x00\x14ftypqt  ', 'mov', True),
        (b'\x1a\x45\xdf\xa3' + b'\x00' * 8, 'webm', True),
        (b'RIFF\x00\x00\x00\x00AVI ', 'avi', True),
        (b'MZ\x90\x00' + b'\x00' * 8, 'mp4', False),
        (b'RIFF\x00\x00\x00\x00WAVE', 'avi', False),
        (b'\x00\x00\x00\x18ftypmp42', 'exe', False),
    ])
    def test_signature_matches_extension(self, header, extension, valid):
        """ Container magic bytes must agree with the claimed type """
        assert has_valid_signature(header, extension) is valid
