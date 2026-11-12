import errno
import hashlib
import os
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from events.models import UploadSession, VideoAsset
from events.tests.test_staff_apis import fake_ffmpeg
from events.tests.test_uploads import UPLOADING, make_video, send_chunk, upload_in_chunks
from events.v1.transcoding import TranscodeError, partial_output_path
from events.v1.uploads import cleanup_sessions, finalize_session, part_path


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

    def test_unremovable_orphan_does_not_abort_sweep(self, upload_root, caplog):
        """ An OSError on one partial file is logged and the other orphans are still removed """
        stuck = upload_root / '3f2b8c9e-1b0a-4c75-9d56-0d4c4f2d1e11.part'
        stale = upload_root / '4f2b8c9e-1b0a-4c75-9d56-0d4c4f2d1e11.part'
        upload_root.mkdir(parents=True, exist_ok=True)
        ancient = time.time() - 7200
        for path in (stuck, stale):
            path.write_bytes(b'x')
            os.utime(path, (ancient, ancient))
        real_unlink = Path.unlink

        def unlink_denied(path, *args, **kwargs):
            if path.name == stuck.name:
                raise PermissionError(errno.EACCES, 'denied', str(path))
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', unlink_denied), caplog.at_level('ERROR', logger='asp_api'):
            summary = cleanup_sessions()

        assert summary['orphan_files_removed'] == 1
        assert stuck.exists()
        assert not stale.exists()
        assert f'upload_orphan_remove_failed file={stuck.name}' in caplog.text

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

    def test_stalled_finalization_is_not_failed_early(self, staff_client, session_for, settings):
        """ A session inside the finalization deadline is only re-queued, never failed """
        data = make_video(100)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data)
        stale = timezone.now() - timedelta(hours=settings.RESUMABLE_UPLOAD_FINALIZE_TIMEOUT_HOURS - 1)
        UploadSession.objects.filter(pk=session.pk).update(modified=stale)

        with patch('events.v1.uploads.current_app.send_task'):
            summary = cleanup_sessions()

        session.refresh_from_db()
        assert summary['finalizations_failed'] == 0
        assert session.status == UploadSession.UploadStatus.FINALIZING

    def test_stuck_finalization_is_failed(
        self, staff_client, session_for, settings, django_capture_on_commit_callbacks
    ):
        """ A session that stays FINALIZING past the deadline fails, is not re-queued and loses its partial file """
        data = make_video(100)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data)
        expired = timezone.now() - timedelta(hours=settings.RESUMABLE_UPLOAD_FINALIZE_TIMEOUT_HOURS + 1)
        UploadSession.objects.filter(pk=session.pk).update(modified=expired)

        with patch('events.v1.uploads.current_app.send_task') as send_task, \
                django_capture_on_commit_callbacks(execute=True):
            summary = cleanup_sessions()

        session.refresh_from_db()
        assert summary['finalizations_failed'] == 1
        assert summary['finalizations_redispatched'] == 0
        assert session.status == UploadSession.UploadStatus.FAILED
        assert session.error_code == 'finalize_timeout'
        assert not part_path(session.id).exists()
        send_task.assert_not_called()

    def test_stuck_finalization_removes_promoted_file(
        self, staff_client, session_for, settings, media_storage, django_capture_on_commit_callbacks
    ):
        """ A file a crashed finalization already moved into the video storage is removed with its session """
        data = make_video(100)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data)
        promoted = media_storage / 'video_file' / f'{session.id}.mp4'
        promoted.parent.mkdir(parents=True, exist_ok=True)
        part_path(session.id).rename(promoted)
        expired = timezone.now() - timedelta(hours=settings.RESUMABLE_UPLOAD_FINALIZE_TIMEOUT_HOURS + 1)
        UploadSession.objects.filter(pk=session.pk).update(modified=expired)

        with django_capture_on_commit_callbacks(execute=True):
            cleanup_sessions()

        assert not promoted.exists()

    def test_stuck_finalization_removes_partial_output(
        self, staff_client, session_for, settings, media_storage, django_capture_on_commit_callbacks
    ):
        """ A stuck session fails and both its converted file and a half-written conversion are removed """
        data = make_video(100)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data)
        promoted = media_storage / 'video_file' / f'{session.id}.mp4'
        leftover = partial_output_path(promoted)
        promoted.parent.mkdir(parents=True, exist_ok=True)
        promoted.write_bytes(b'converted')
        leftover.write_bytes(b'half written')
        expired = timezone.now() - timedelta(hours=settings.RESUMABLE_UPLOAD_FINALIZE_TIMEOUT_HOURS + 1)
        UploadSession.objects.filter(pk=session.pk).update(modified=expired)

        with django_capture_on_commit_callbacks(execute=True):
            summary = cleanup_sessions()

        session.refresh_from_db()
        assert summary['finalizations_failed'] == 1
        assert (session.status, session.error_code) == (UploadSession.UploadStatus.FAILED, 'finalize_timeout')
        assert not promoted.exists()
        assert not leftover.exists()

    def test_stuck_finalization_without_files_is_failed(
        self, staff_client, session_for, settings, media_storage, django_capture_on_commit_callbacks
    ):
        """ Removing files that are already gone is a no-op and does not stop the session from failing """
        data = make_video(100)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data)
        expired = timezone.now() - timedelta(hours=settings.RESUMABLE_UPLOAD_FINALIZE_TIMEOUT_HOURS + 1)
        UploadSession.objects.filter(pk=session.pk).update(modified=expired)

        with django_capture_on_commit_callbacks(execute=True):
            summary = cleanup_sessions()

        session.refresh_from_db()
        assert summary['finalizations_failed'] == 1
        assert session.status == UploadSession.UploadStatus.FAILED
        assert not list((media_storage / 'video_file').glob('*'))

    def test_locked_stuck_finalization_is_skipped(self, staff_client, session_for, settings):
        """ A session a worker is finalizing right now is left for that worker """
        data = make_video(100)
        session = session_for(data)
        send_chunk(staff_client, session.id, 0, data)
        expired = timezone.now() - timedelta(hours=settings.RESUMABLE_UPLOAD_FINALIZE_TIMEOUT_HOURS + 1)
        UploadSession.objects.filter(pk=session.pk).update(modified=expired)

        with patch('events.v1.uploads.UploadSession.objects.select_for_update') as select_for_update, \
                patch('events.v1.uploads.current_app.send_task'):
            select_for_update.return_value.filter.return_value.first.return_value = None
            summary = cleanup_sessions()

        session.refresh_from_db()
        assert summary['finalizations_failed'] == 0
        assert session.status == UploadSession.UploadStatus.FINALIZING

    def test_management_command_reports_summary(self, capsys):
        """ The command is a thin wrapper that prints the cleanup summary """
        call_command('cleanup_upload_sessions')

        assert 'expired: 0' in capsys.readouterr().out


@pytest.mark.django_db
class TestFinalizationFileCleanup:
    """ Files left by a failed finalization are removed only once the transaction has committed """

    @pytest.fixture(autouse=True)
    def storage(self, media_storage, upload_root):  # pylint: disable=unused-argument
        """ Keep promoted videos and partial files in temporary directories """

    @staticmethod
    def finished_session(staff_client, session_for, data, **overrides):
        """ A session whose bytes have all been uploaded """
        session = session_for(data, **overrides)
        upload_in_chunks(staff_client, session.id, data, 128)
        session.refresh_from_db()
        return session

    def test_discarded_files_are_removed_after_commit(
        self, staff_client, session_for, media_storage, django_capture_on_commit_callbacks
    ):
        """ The asset row goes at once, its video and thumbnail only once the transaction has committed """
        session = self.finished_session(staff_client, session_for, make_video(500))
        video = media_storage / 'video_file' / f'{session.id}.mp4'

        with patch('events.models.ffmpeg', fake_ffmpeg(0)), django_capture_on_commit_callbacks() as callbacks:
            result = finalize_session(session.id)

        thumbnails = list((media_storage / 'thumbnail').glob('*'))
        assert result.video_asset_id is None
        assert not VideoAsset.objects.exists()
        assert video.exists()
        assert len(thumbnails) == 1
        for callback in callbacks:
            callback()
        assert not video.exists()
        assert not thumbnails[0].exists()
        assert not part_path(session.id).exists()

    def test_discard_is_undone_when_transaction_rolls_back(
        self, staff_client, session_for, media_storage, django_capture_on_commit_callbacks
    ):
        """ A rollback registers no file removal, so the retry finds the promoted file under its fixed name """
        session = self.finished_session(staff_client, session_for, make_video(500))

        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with patch('events.models.ffmpeg', fake_ffmpeg(0)), pytest.raises(RuntimeError):
                with transaction.atomic():
                    finalize_session(session.id)
                    raise RuntimeError('rollback')

        assert not callbacks
        assert (media_storage / 'video_file' / f'{session.id}.mp4').exists()
        assert not VideoAsset.objects.exists()
        session.refresh_from_db()
        assert session.status == UploadSession.UploadStatus.FINALIZING

    def test_failed_session_keeps_part_until_commit(
        self, staff_client, session_for, django_capture_on_commit_callbacks
    ):
        """ The partial file of a failed session is removed by an on_commit callback, not inline """
        session = self.finished_session(
            staff_client, session_for, make_video(500), checksum_sha256=hashlib.sha256(b'other').hexdigest()
        )

        with django_capture_on_commit_callbacks() as callbacks:
            result = finalize_session(session.id)

        assert result.error_code == 'checksum_mismatch'
        assert part_path(session.id).exists()
        for callback in callbacks:
            callback()
        assert not part_path(session.id).exists()

    def test_failure_rolled_back_keeps_part(self, staff_client, session_for, django_capture_on_commit_callbacks):
        """ If the transaction that failed the session rolls back, the partial file is not removed """
        session = self.finished_session(
            staff_client, session_for, make_video(500), checksum_sha256=hashlib.sha256(b'other').hexdigest()
        )

        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    finalize_session(session.id)
                    raise RuntimeError('rollback')

        assert not callbacks
        assert part_path(session.id).exists()
        session.refresh_from_db()
        assert session.status == UploadSession.UploadStatus.FINALIZING

    @staticmethod
    def leave_file(media_storage, name, content):
        """ Put a file in the video storage, as a crashed conversion would have """
        path = media_storage / 'video_file' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    @staticmethod
    def finalize_with_probe(session):
        """ Finalize with the ffmpeg probe stubbed to a 90 second video """
        with patch('events.models.ffmpeg', fake_ffmpeg(90)):
            return finalize_session(session.id)

    def test_part_and_destination_are_reconverted(self, staff_client, session_for, media_storage):
        """ A crash between os.replace and part.unlink leaves both files: the part is converted again """
        data = make_video(500)
        session = self.finished_session(staff_client, session_for, data)
        destination = self.leave_file(media_storage, f'{session.id}.mp4', b'stale conversion')

        result = self.finalize_with_probe(session)

        assert result.status == UploadSession.UploadStatus.COMPLETED
        assert destination.read_bytes() == data
        assert not part_path(session.id).exists()
        assert list(destination.parent.glob('*')) == [destination]

    def test_part_and_destination_are_reverified(self, staff_client, session_for, media_storage):
        """ With both files present the part is still checked, so a truncated one fails the session """
        session = self.finished_session(staff_client, session_for, make_video(500))
        self.leave_file(media_storage, f'{session.id}.mp4', b'stale conversion')
        with open(part_path(session.id), 'r+b') as handle:
            handle.truncate(400)

        result = finalize_session(session.id)

        assert (result.status, result.error_code) == (UploadSession.UploadStatus.FAILED, 'size_mismatch')
        assert VideoAsset.objects.count() == 0

    def test_killed_conversion_leftover_is_harmless(self, staff_client, session_for, media_storage):
        """ A .partial.mp4 left by a killed conversion does not stop a fresh finalization """
        data = make_video(500)
        session = self.finished_session(staff_client, session_for, data)
        self.leave_file(media_storage, f'{session.id}.partial.mp4', b'half written')

        result = self.finalize_with_probe(session)

        assert result.status == UploadSession.UploadStatus.COMPLETED
        assert VideoAsset.objects.get(pk=result.video_asset_id).status == VideoAsset.VideoStatus.READY
        assert (media_storage / 'video_file' / f'{session.id}.mp4').read_bytes() == data

    def test_conversion_error_fails_the_session(
        self, staff_client, session_for, media_storage, django_capture_on_commit_callbacks
    ):
        """ A TranscodeError fails the session with processing_failed and publishes nothing """
        session = self.finished_session(staff_client, session_for, make_video(500))

        with patch('events.v1.uploads.make_web_playable', side_effect=TranscodeError('boom')):
            with django_capture_on_commit_callbacks(execute=True):
                result = self.finalize_with_probe(session)

        assert result.status == UploadSession.UploadStatus.FAILED
        assert (result.error_code, result.video_asset_id) == ('processing_failed', None)
        assert VideoAsset.objects.count() == 0
        assert not part_path(session.id).exists()
        assert not (media_storage / 'video_file' / f'{session.id}.mp4').exists()
