import errno
import os
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from django.core.management import call_command
from django.utils import timezone

from events.models import UploadSession
from events.tests.test_uploads import UPLOADING, make_video, send_chunk
from events.v1.uploads import cleanup_sessions, part_path


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
