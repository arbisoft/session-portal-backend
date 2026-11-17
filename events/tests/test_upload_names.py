import os
import re
from io import StringIO
from unittest import mock

import pytest

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.db import DatabaseError

from events.models import VideoAsset, unguessable_upload_name

UUID_NAME = re.compile(r'^[0-9a-f]{32}\.[a-z0-9]+$')


class TestUnguessableUploadName:
    """ Stored video and thumbnail names never come from the client """

    def test_name_is_uuid_plus_lowercased_extension(self):
        """ Only the extension survives from the client's name """
        name = unguessable_upload_name(None, 'All_Hands_2026.MOV')

        assert UUID_NAME.match(name)
        assert name.endswith('.mov')
        assert 'All_Hands' not in name

    def test_names_are_unique_for_the_same_filename(self):
        """ Two uploads of the same file never collide or reveal each other """
        assert unguessable_upload_name(None, 'talk.mp4') != unguessable_upload_name(None, 'talk.mp4')

    def test_directories_in_the_client_name_are_dropped(self):
        """ A path in the client name cannot influence where the file is stored """
        name = unguessable_upload_name(None, '../../etc/passwd.mp4')

        assert UUID_NAME.match(name)

    @pytest.mark.usefixtures('media_storage')
    def test_saved_files_get_uuid_names(self):
        """ Both fields store under random names, and the thumbnail does not share the video's """
        asset = VideoAsset(title='Quarterly Review')

        asset.video_file.save('Quarterly Review.mp4', ContentFile(b'video'), save=False)
        asset.thumbnail.save('Quarterly Review_thumb.jpg', ContentFile(b'image'), save=False)

        assert UUID_NAME.match(asset.video_file.name)
        assert UUID_NAME.match(asset.thumbnail.name)
        assert asset.video_file.name.rsplit('.', 1)[0] != asset.thumbnail.name.rsplit('.', 1)[0]


@pytest.mark.django_db
class TestRenameMediaFilesCommand:
    """ Existing guessable files are renamed and their rows updated """

    @staticmethod
    def stored_asset(tmp_path, monkeypatch, video_name='video_280.mp4', thumbnail_name='video_280_thumb.jpg'):
        """
        An asset whose video and thumbnail sit on disk under the given (by default guessable) names

        A ``thumbnail_name`` of ``None`` gives an asset with an empty thumbnail and no thumbnail file.
        """
        names = {'video_file': video_name, 'thumbnail': thumbnail_name}
        for field_name, name in names.items():
            field = VideoAsset._meta.get_field(field_name)  # pylint: disable=protected-access
            monkeypatch.setattr(field, 'storage', FileSystemStorage(location=tmp_path / field_name))
            if name is None:
                continue
            path = tmp_path / field_name / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'data')
        asset = VideoAsset.objects.create(title='All Hands', status=VideoAsset.VideoStatus.READY)
        VideoAsset.objects.filter(pk=asset.pk).update(**{key: value or '' for key, value in names.items()})
        return asset

    def test_files_and_rows_get_uuid_names(self, tmp_path, monkeypatch):
        """ The guessable names are gone from disk and from the database """
        asset = self.stored_asset(tmp_path, monkeypatch)

        call_command('rename_media_files', stdout=StringIO())

        asset.refresh_from_db()
        assert UUID_NAME.match(asset.video_file.name)
        assert UUID_NAME.match(asset.thumbnail.name)
        assert not (tmp_path / 'video_file' / 'video_280.mp4').exists()
        assert (tmp_path / 'video_file' / asset.video_file.name).read_bytes() == b'data'
        assert (tmp_path / 'thumbnail' / asset.thumbnail.name).exists()

    def test_dry_run_changes_nothing(self, tmp_path, monkeypatch):
        """ A dry run only reports """
        asset = self.stored_asset(tmp_path, monkeypatch)

        call_command('rename_media_files', '--dry-run', stdout=StringIO())

        asset.refresh_from_db()
        assert asset.video_file.name == 'video_280.mp4'
        assert (tmp_path / 'video_file' / 'video_280.mp4').exists()

    def test_second_run_leaves_renamed_files_alone(self, tmp_path, monkeypatch):
        """ Running again does not rename a file twice """
        asset = self.stored_asset(tmp_path, monkeypatch)
        call_command('rename_media_files', stdout=StringIO())
        asset.refresh_from_db()
        first_name = asset.video_file.name

        call_command('rename_media_files', stdout=StringIO())

        asset.refresh_from_db()
        assert asset.video_file.name == first_name

    def test_dry_run_summary_lists_would_be_renames(self, tmp_path, monkeypatch):
        """ The dry run names each file and says how many would be renamed """
        asset = self.stored_asset(tmp_path, monkeypatch)
        output = StringIO()

        call_command('rename_media_files', '--dry-run', stdout=output)

        assert f'#{asset.pk} video_file: would rename video_280.mp4' in output.getvalue()
        assert f'#{asset.pk} thumbnail: would rename video_280_thumb.jpg' in output.getvalue()
        assert '2 would be renamed, 0 already unguessable or empty, 0 failed' in output.getvalue()

    def test_asset_ids_limit_the_renames(self, tmp_path, monkeypatch):
        """ Only the listed asset is renamed """
        listed = self.stored_asset(tmp_path, monkeypatch)
        other = self.stored_asset(tmp_path, monkeypatch, 'video_281.mp4', 'video_281_thumb.jpg')

        call_command('rename_media_files', str(listed.pk), stdout=StringIO())

        listed.refresh_from_db()
        other.refresh_from_db()
        assert UUID_NAME.match(listed.video_file.name)
        assert other.video_file.name == 'video_281.mp4'
        assert other.thumbnail.name == 'video_281_thumb.jpg'
        assert (tmp_path / 'video_file' / 'video_281.mp4').exists()

    def test_missing_source_file_counts_as_failed(self, tmp_path, monkeypatch):
        """ A row whose file is gone is reported and left untouched """
        asset = self.stored_asset(tmp_path, monkeypatch)
        (tmp_path / 'video_file' / 'video_280.mp4').unlink()
        output = StringIO()

        call_command('rename_media_files', stdout=output)

        asset.refresh_from_db()
        assert asset.video_file.name == 'video_280.mp4'
        assert UUID_NAME.match(asset.thumbnail.name)
        assert 'video_280.mp4 is missing, skipped' in output.getvalue()
        assert '1 renamed, 0 already unguessable or empty, 1 failed' in output.getvalue()

    def test_db_error_renames_the_file_back(self, tmp_path, monkeypatch):
        """ When the row cannot be updated, the file returns to its old name and the row is unchanged """
        asset = self.stored_asset(tmp_path, monkeypatch)
        output = StringIO()

        with mock.patch.object(VideoAsset.objects, 'filter', side_effect=DatabaseError('boom')):
            call_command('rename_media_files', stdout=output)

        asset.refresh_from_db()
        assert asset.video_file.name == 'video_280.mp4'
        assert asset.thumbnail.name == 'video_280_thumb.jpg'
        assert [path.name for path in (tmp_path / 'video_file').iterdir()] == ['video_280.mp4']
        assert [path.name for path in (tmp_path / 'thumbnail').iterdir()] == ['video_280_thumb.jpg']
        assert '0 renamed, 0 already unguessable or empty, 2 failed' in output.getvalue()

    def test_row_changed_midrun_renames_file_back(self, tmp_path, monkeypatch):
        """ A row that changed after the snapshot matches 0 rows, so the file goes back and the row keeps its name """
        asset = self.stored_asset(tmp_path, monkeypatch)
        real_name = unguessable_upload_name

        def change_row_then_name(instance, filename):
            if filename == 'video_280.mp4':
                VideoAsset.objects.filter(pk=instance.pk).update(video_file='other.mp4')
            return real_name(instance, filename)

        output = StringIO()
        with mock.patch('events.management.commands.rename_media_files.unguessable_upload_name',
                        side_effect=change_row_then_name):
            call_command('rename_media_files', stdout=output)

        asset.refresh_from_db()
        assert asset.video_file.name == 'other.mp4'
        assert UUID_NAME.match(asset.thumbnail.name)
        assert [path.name for path in (tmp_path / 'video_file').iterdir()] == ['video_280.mp4']
        assert '1 renamed, 0 already unguessable or empty, 1 failed' in output.getvalue()

    def test_failed_rollback_is_logged_and_run_continues(self, tmp_path, monkeypatch):
        """ If the file cannot be renamed back, the failure is logged, shown to the operator, and the run finishes """
        asset = self.stored_asset(tmp_path, monkeypatch)
        real_rename = os.rename
        old_names = {'video_280.mp4', 'video_280_thumb.jpg'}

        def rename_unless_rolling_back(source, target):
            if os.path.basename(target) in old_names:
                raise OSError('disk gone')
            real_rename(source, target)

        output = StringIO()
        with mock.patch('events.management.commands.rename_media_files.logger') as logger, \
                mock.patch('events.management.commands.rename_media_files.os.rename',
                           side_effect=rename_unless_rolling_back), \
                mock.patch.object(VideoAsset.objects, 'filter', side_effect=DatabaseError('boom')):
            call_command('rename_media_files', stdout=output)

        asset.refresh_from_db()
        assert asset.video_file.name == 'video_280.mp4'
        assert asset.thumbnail.name == 'video_280_thumb.jpg'
        logged = [call.args[0] for call in logger.exception.call_args_list]
        assert logged.count('rename_media_rollback_failed asset=%s source=%s target=%s') == 2
        assert '0 renamed, 0 already unguessable or empty, 2 failed' in output.getvalue()
        for field_name, old_name, extension in (('video_file', 'video_280.mp4', 'mp4'),
                                                ('thumbnail', 'video_280_thumb.jpg', 'jpg')):
            directory = tmp_path / field_name
            assert re.search(
                re.escape(f'#{asset.pk} {field_name}: rollback failed, file is at {directory}/')
                + rf'[0-9a-f]{{32}}\.{extension}'
                + re.escape(f', move it back to {directory / old_name}'),
                output.getvalue(),
            )

    def test_forward_rename_error_counts_as_failed(self, tmp_path, monkeypatch):
        """ When the rename itself fails the file and row stay as they were and the run goes on to the thumbnail """
        asset = self.stored_asset(tmp_path, monkeypatch)
        real_rename = os.rename

        def fail_for_video(source, target):
            if os.path.basename(source) == 'video_280.mp4':
                raise OSError('read-only')
            real_rename(source, target)

        output = StringIO()
        with mock.patch('events.management.commands.rename_media_files.logger') as logger, \
                mock.patch('events.management.commands.rename_media_files.os.rename', side_effect=fail_for_video):
            call_command('rename_media_files', stdout=output)

        asset.refresh_from_db()
        assert asset.video_file.name == 'video_280.mp4'
        assert [path.name for path in (tmp_path / 'video_file').iterdir()] == ['video_280.mp4']
        assert UUID_NAME.match(asset.thumbnail.name)
        assert (tmp_path / 'thumbnail' / asset.thumbnail.name).exists()
        logged = [call.args[0] for call in logger.exception.call_args_list]
        assert logged == ['rename_media_failed asset=%s field=%s']
        assert 'rollback failed' not in output.getvalue()
        assert '1 renamed, 0 already unguessable or empty, 1 failed' in output.getvalue()

    def test_empty_thumbnail_is_skipped(self, tmp_path, monkeypatch):
        """ An asset without a thumbnail has its video renamed, the empty field is skipped and nothing fails """
        asset = self.stored_asset(tmp_path, monkeypatch, thumbnail_name=None)
        output = StringIO()

        call_command('rename_media_files', stdout=output)

        asset.refresh_from_db()
        assert UUID_NAME.match(asset.video_file.name)
        assert (tmp_path / 'video_file' / asset.video_file.name).read_bytes() == b'data'
        assert not asset.thumbnail
        assert '1 renamed, 1 already unguessable or empty, 0 failed' in output.getvalue()

    def test_subdirectory_is_kept_on_rename(self, tmp_path, monkeypatch):
        """ A file stays in its sub-directory and the row keeps the directory prefix """
        asset = self.stored_asset(tmp_path, monkeypatch, video_name='2024/talk.mp4')

        call_command('rename_media_files', stdout=StringIO())

        asset.refresh_from_db()
        assert os.path.dirname(asset.video_file.name) == '2024'
        assert UUID_NAME.match(os.path.basename(asset.video_file.name))
        assert (tmp_path / 'video_file' / asset.video_file.name).read_bytes() == b'data'
        assert not (tmp_path / 'video_file' / '2024' / 'talk.mp4').exists()
        assert [path.name for path in (tmp_path / 'video_file').iterdir()] == ['2024']

    def test_dashed_session_uuid_names_are_skipped(self, tmp_path, monkeypatch):
        """ Resumable uploads are stored as <session uuid>.mp4 and are already unguessable """
        session_name = '123e4567-e89b-12d3-a456-426614174000.mp4'
        asset = self.stored_asset(tmp_path, monkeypatch, video_name=session_name)
        output = StringIO()

        call_command('rename_media_files', stdout=output)

        asset.refresh_from_db()
        assert asset.video_file.name == session_name
        assert (tmp_path / 'video_file' / session_name).exists()
        assert '1 renamed, 1 already unguessable or empty, 0 failed' in output.getvalue()
