import shutil
import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import ffmpeg
import pytest

from django.core.management import call_command

from events.models import UploadSession, VideoAsset
from events.tests.test_uploads import upload_in_chunks
from events.v1 import transcoding, uploads
from events.v1.transcoding import (
    ConversionPlan,
    TranscodeError,
    build_command,
    make_web_playable,
    partial_output_path,
    plan_conversion,
)
from events.v1.uploads import finalize_session, part_path

needs_ffmpeg = pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='the ffmpeg binary is not installed')


def probe_result(video=None, audio=None):
    """ Minimal ``ffmpeg.probe`` output with the given streams """
    streams = []
    if video:
        streams.append({'index': 0, 'codec_type': 'video', **video})
    if audio:
        streams.append({'index': 1, 'codec_type': 'audio', **audio})
    return {'streams': streams}


class TestConversionPlan:
    """ Which streams are copied and which are re-encoded """

    def test_web_safe_streams_are_copied(self):
        """ H.264 4:2:0 and AAC only need repackaging """
        plan = plan_conversion(probe_result({'codec_name': 'h264', 'pix_fmt': 'yuv420p'}, {'codec_name': 'aac'}))

        assert plan.copy_video and plan.copy_audio

    @pytest.mark.parametrize('video', [
        {'codec_name': 'mpeg4', 'pix_fmt': 'yuv420p'},
        {'codec_name': 'vp8', 'pix_fmt': 'yuv420p'},
        {'codec_name': 'prores', 'pix_fmt': 'yuv422p10le'},
        {'codec_name': 'hevc', 'pix_fmt': 'yuv420p'},
        {'codec_name': 'h264', 'pix_fmt': 'yuv422p10le'},
    ])
    def test_other_video_is_re_encoded(self, video):
        """ Codecs or pixel formats a browser cannot play everywhere are converted """
        assert not plan_conversion(probe_result(video, {'codec_name': 'aac'})).copy_video

    @pytest.mark.parametrize('codec', ['mp3', 'vorbis', 'opus', 'pcm_s16le', 'ac3'])
    def test_other_audio_is_re_encoded(self, codec):
        """ Only AAC audio is kept as it is """
        plan = plan_conversion(probe_result({'codec_name': 'h264', 'pix_fmt': 'yuv420p'}, {'codec_name': codec}))

        assert not plan.copy_audio

    def test_a_silent_video_has_no_audio_stream(self):
        """ No audio is not an error """
        plan = plan_conversion(probe_result({'codec_name': 'h264', 'pix_fmt': 'yuv420p'}))

        assert plan.audio_index is None

    def test_cover_art_is_not_the_video(self):
        """ An audio file with an embedded picture has no video to play """
        probe = probe_result({'codec_name': 'mjpeg', 'pix_fmt': 'yuvj420p', 'disposition': {'attached_pic': 1}})

        with pytest.raises(TranscodeError):
            plan_conversion(probe)


def test_command_logs_errors_only_without_stats():
    """ Only errors are logged and no progress stats are written, so the captured stderr stays small """
    plan = ConversionPlan(video_index=0, copy_video=True, audio_index=None, copy_audio=False)

    command = build_command(Path('in.avi'), Path('out.mp4'), plan)

    assert command[command.index('-loglevel') + 1] == 'error'
    assert '-nostats' in command
    assert command.index('-loglevel') < command.index('-i')
    assert command.index('-nostats') < command.index('-i')


class TestMakeWebPlayable:
    """ Behaviour around ffmpeg that does not need a real video """

    def test_unreadable_file_is_an_error(self, tmp_path):
        """ ffmpeg refusing to read the file means it would not play """
        source = tmp_path / 'bad.avi'
        source.write_bytes(b'not a video')

        with patch.object(transcoding.ffmpeg, 'probe', side_effect=ffmpeg.Error('probe', b'', b'bad')):
            with pytest.raises(TranscodeError):
                make_web_playable(source, tmp_path / 'out.mp4')

        assert not (tmp_path / 'out.mp4').exists()

    def test_failed_conversion_leaves_no_output(self, tmp_path):
        """ A half-written output is removed and never renamed into place """
        source = tmp_path / 'in.avi'
        source.write_bytes(b'x')
        destination = tmp_path / 'out' / 'video.mp4'

        def fail(command, **kwargs):  # pylint: disable=unused-argument
            Path(command[-1]).write_bytes(b'partial')
            raise subprocess.CalledProcessError(1, command, stderr=b'boom')

        probe = probe_result({'codec_name': 'vp8', 'pix_fmt': 'yuv420p'}, {'codec_name': 'vorbis'})
        with patch.object(transcoding.ffmpeg, 'probe', return_value=probe), patch.object(subprocess, 'run', fail):
            with pytest.raises(TranscodeError):
                make_web_playable(source, destination)

        assert not destination.exists()
        assert not list(destination.parent.glob('*.partial.mp4'))
        assert source.exists()

    def test_timeout_is_an_error(self, tmp_path):
        """ A conversion that runs past the limit is abandoned """
        source = tmp_path / 'in.avi'
        source.write_bytes(b'x')

        probe = probe_result({'codec_name': 'vp8', 'pix_fmt': 'yuv420p'})
        with patch.object(transcoding.ffmpeg, 'probe', return_value=probe):
            with patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffmpeg', 1)):
                with pytest.raises(TranscodeError):
                    make_web_playable(source, tmp_path / 'out.mp4')


def test_partial_output_is_a_sibling_of_destination():
    """ The half-written conversion sits next to the destination under its own name, so it can never replace it """
    destination = Path('x/abc.mp4')

    partial = partial_output_path(destination)

    assert partial.parent == destination.parent
    assert partial.name == 'abc.partial.mp4'
    assert partial != destination


def encode(path, *args, size='320x240'):
    """ Generate a two second test clip with a tone, using the given extra ffmpeg arguments """
    subprocess.run(
        ['ffmpeg', '-nostdin', '-y', '-f', 'lavfi', '-i', f'testsrc=size={size}:rate=25:duration=2',
         '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', *args, str(path)],
        check=True, capture_output=True,
    )
    return path


def codecs(path):
    """ Codec names, pixel format and container of a file, as a browser would meet them """
    info = ffmpeg.probe(str(path))
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    audio = [s for s in info['streams'] if s['codec_type'] == 'audio']
    return {
        'video': video['codec_name'], 'pix_fmt': video['pix_fmt'], 'width': video['width'], 'height': video['height'],
        'audio': audio[0]['codec_name'] if audio else None,
        'container': info['format']['format_name'], 'duration': float(info['format']['duration']),
    }


@needs_ffmpeg
class TestRealConversion:
    """ The formats from the playback report, converted by the real ffmpeg """

    FORMATS = {
        'avi_mpeg4': ('clip.avi', ['-c:v', 'mpeg4', '-c:a', 'libmp3lame']),
        'webm_vp8': ('clip.webm', ['-c:v', 'libvpx', '-c:a', 'libvorbis']),
        'mov_prores': ('clip.mov', ['-c:v', 'prores_ks', '-pix_fmt', 'yuv422p10le', '-c:a', 'pcm_s16le']),
        'mov_h264': ('clip.mov', ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac']),
        'mp4_h264_mp3': ('clip.mp4', ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'libmp3lame']),
    }

    @pytest.mark.parametrize('name', FORMATS)
    def test_every_format_becomes_h264_aac_mp4(self, tmp_path, name):
        """ Whatever came in, the result is an MP4 with H.264 4:2:0 video and AAC audio of the same length """
        filename, args = self.FORMATS[name]
        try:
            source = encode(tmp_path / filename, *args)
        except subprocess.CalledProcessError:
            pytest.skip(f'this ffmpeg build cannot create {name}')
        destination = tmp_path / 'converted' / 'video.mp4'

        make_web_playable(source, destination)

        result = codecs(destination)
        assert result['video'] == 'h264'
        assert result['pix_fmt'] == 'yuv420p'
        assert result['audio'] == 'aac'
        assert 'mp4' in result['container']
        assert result['duration'] == pytest.approx(2, abs=0.3)
        assert (result['width'], result['height']) == (320, 240)
        assert source.exists()

    def test_odd_dimensions_are_rounded_down_to_even(self, tmp_path):
        """ H.264 in 4:2:0 cannot have odd sides, which phone and screen recordings sometimes do """
        source = encode(tmp_path / 'odd.avi', '-c:v', 'mpeg4', '-c:a', 'libmp3lame', size='321x241')

        make_web_playable(source, tmp_path / 'video.mp4')

        assert (codecs(tmp_path / 'video.mp4')['width'], codecs(tmp_path / 'video.mp4')['height']) == (320, 240)

    def test_index_is_moved_to_the_front(self, tmp_path):
        """ +faststart puts the moov atom before the media data """
        source = encode(tmp_path / 'clip.mov', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac')
        destination = tmp_path / 'video.mp4'

        make_web_playable(source, destination)

        head = destination.read_bytes()[:4096]
        assert head.find(b'moov') != -1
        assert head.find(b'moov') < destination.read_bytes().find(b'mdat')

    def test_a_silent_video_converts(self, tmp_path):
        """ No audio track is fine """
        source = tmp_path / 'silent.avi'
        subprocess.run(
            ['ffmpeg', '-nostdin', '-y', '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=25:duration=1',
             '-c:v', 'mpeg4', str(source)], check=True, capture_output=True,
        )

        make_web_playable(source, tmp_path / 'video.mp4')

        assert codecs(tmp_path / 'video.mp4')['audio'] is None

    def test_random_bytes_are_rejected(self, tmp_path):
        """ A file that only pretends to be a video fails instead of being published """
        source = tmp_path / 'fake.avi'
        source.write_bytes(b'RIFF' + bytes(200))

        with pytest.raises(TranscodeError):
            make_web_playable(source, tmp_path / 'video.mp4')


@pytest.mark.django_db
@needs_ffmpeg
class TestFinalizationConverts:
    """ Finalization stores the converted MP4, whatever the upload was """

    @pytest.fixture(autouse=True)
    def real_conversion(self, monkeypatch, media_storage, upload_root):  # pylint: disable=unused-argument
        """ Undo the conftest stub: these tests run the real conversion """
        monkeypatch.setattr(uploads, 'make_web_playable', make_web_playable)

    def finished_session(self, staff_client, session_for, source):
        """ A session whose bytes are those of ``source`` """
        data = source.read_bytes()
        session = session_for(data, filename=source.name)
        upload_in_chunks(staff_client, session.id, data, 64 * 1024)
        session.refresh_from_db()
        return session

    def test_an_avi_is_stored_as_a_playable_mp4(self, staff_client, session_for, tmp_path, media_storage):
        """ The reported AVI case: the stored file is an H.264/AAC MP4 and the asset is ready with a duration """
        source = encode(tmp_path / 'talk.avi', '-c:v', 'mpeg4', '-c:a', 'libmp3lame')
        session = self.finished_session(staff_client, session_for, source)

        result = finalize_session(session.id)

        assert result.status == UploadSession.UploadStatus.COMPLETED
        stored = media_storage / 'video_file' / f'{session.id}.mp4'
        assert codecs(stored)['video'] == 'h264'
        assert codecs(stored)['audio'] == 'aac'
        asset = VideoAsset.objects.get(pk=result.video_asset_id)
        assert asset.status == VideoAsset.VideoStatus.READY
        assert asset.video_file.name.endswith('.mp4')
        assert asset.duration in (1, 2)
        assert not part_path(session.id).exists()
        assert not (media_storage / 'video_file' / f'{session.id}.avi').exists()

    def test_unconvertible_file_fails_the_session(
        self, staff_client, session_for, tmp_path, media_storage
    ):
        """ Correct extension and signature but no decodable video: nothing is published and nothing is left behind """
        header = b'RIFF\x00\x00\x00\x00AVI ' + bytes(500)
        source = tmp_path / 'broken.avi'
        source.write_bytes(header)
        session = self.finished_session(staff_client, session_for, source)

        result = finalize_session(session.id)

        assert result.status == UploadSession.UploadStatus.FAILED
        assert result.error_code == 'processing_failed'
        assert not VideoAsset.objects.exists()
        assert not list((media_storage / 'video_file').glob('*'))


@pytest.mark.django_db
@needs_ffmpeg
class TestConvertVideoAssetsCommand:
    """ Backfill for videos stored before uploads were converted """

    @pytest.fixture(autouse=True)
    def storage(self, media_storage):  # pylint: disable=unused-argument
        """ Keep stored videos in a temporary directory """

    @staticmethod
    def stored_asset(media_storage, filename, *args):
        """ An asset whose file is a real clip in the video storage under ``filename`` """
        folder = media_storage / 'video_file'
        folder.mkdir(parents=True, exist_ok=True)
        encode(folder / filename, *args)
        asset = VideoAsset.objects.create(title='Old', status=VideoAsset.VideoStatus.READY)
        VideoAsset.objects.filter(pk=asset.pk).update(video_file=filename)
        return VideoAsset.objects.get(pk=asset.pk)

    def test_an_old_avi_becomes_a_playable_mp4(self, media_storage):
        """ The asset points at the new file and the original is removed """
        asset = self.stored_asset(media_storage, 'old.avi', '-c:v', 'mpeg4', '-c:a', 'libmp3lame')

        call_command('convert_videoassets', stdout=StringIO())

        asset.refresh_from_db()
        assert asset.video_file.name == 'old.mp4'
        assert codecs(media_storage / 'video_file' / 'old.mp4')['video'] == 'h264'
        assert not (media_storage / 'video_file' / 'old.avi').exists()
        assert asset.file_size == (media_storage / 'video_file' / 'old.mp4').stat().st_size

    def test_a_playable_mp4_is_left_alone(self, media_storage):
        """ Nothing is rewritten when the file already plays everywhere """
        asset = self.stored_asset(media_storage, 'fine.mp4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac')
        before = (media_storage / 'video_file' / 'fine.mp4').read_bytes()

        output = StringIO()
        call_command('convert_videoassets', stdout=output)

        assert (media_storage / 'video_file' / 'fine.mp4').read_bytes() == before
        assert '0 converted, 1 already playable' in output.getvalue()
        asset.refresh_from_db()
        assert asset.video_file.name == 'fine.mp4'

    def test_dry_run_changes_nothing(self, media_storage):
        """ A dry run only reports """
        asset = self.stored_asset(media_storage, 'old.avi', '-c:v', 'mpeg4', '-c:a', 'libmp3lame')

        output = StringIO()
        call_command('convert_videoassets', '--dry-run', stdout=output)

        asset.refresh_from_db()
        assert asset.video_file.name == 'old.avi'
        assert (media_storage / 'video_file' / 'old.avi').exists()
        assert 'would convert old.avi' in output.getvalue()

    def test_other_assets_mp4_is_not_overwritten(self, media_storage):
        """ talk.avi becomes a new free name, so an unrelated asset's talk.mp4 stays byte-identical """
        mp4_args = ('-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac')
        converted = self.stored_asset(media_storage, 'talk.avi', '-c:v', 'mpeg4', '-c:a', 'libmp3lame')
        unrelated = self.stored_asset(media_storage, 'talk.mp4', *mp4_args)
        folder = media_storage / 'video_file'
        before = (folder / 'talk.mp4').read_bytes()

        call_command('convert_videoassets', converted.pk, stdout=StringIO())

        converted.refresh_from_db()
        unrelated.refresh_from_db()
        assert (folder / 'talk.mp4').read_bytes() == before
        assert unrelated.video_file.name == 'talk.mp4'
        assert converted.video_file.name not in ('talk.avi', 'talk.mp4')
        assert converted.video_file.name.endswith('.mp4')
        assert codecs(folder / converted.video_file.name)['video'] == 'h264'
        assert not (folder / 'talk.avi').exists()

    def test_hevc_mp4_is_converted_to_a_new_name(self, media_storage):
        """ A non-H.264 .mp4 is not replaced in place and is removed only once the asset points at the new file """
        try:
            asset = self.stored_asset(media_storage, 'old.mp4', '-c:v', 'libx265', '-pix_fmt', 'yuv420p', '-c:a', 'aac')
        except subprocess.CalledProcessError:
            pytest.skip('this ffmpeg build cannot create HEVC')
        folder = media_storage / 'video_file'
        original = folder / 'old.mp4'
        names_when_removed = []
        real_unlink = Path.unlink

        def record_unlink(path, *args, **kwargs):
            if path == original:
                names_when_removed.append(VideoAsset.objects.get(pk=asset.pk).video_file.name)
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', record_unlink):
            call_command('convert_videoassets', stdout=StringIO())

        asset.refresh_from_db()
        assert asset.video_file.name != 'old.mp4'
        assert codecs(folder / asset.video_file.name)['video'] == 'h264'
        assert not original.exists()
        assert names_when_removed == [asset.video_file.name]


@pytest.mark.django_db
class TestConvertAssetChangedMidway:
    """ An asset edited or deleted while its video converts keeps the original and loses the new file """

    @pytest.fixture(autouse=True)
    def storage(self, media_storage):  # pylint: disable=unused-argument
        """ Keep stored videos in a temporary directory """

    @staticmethod
    def change_row(pk, how):
        """ Repoint the asset at another file or delete it, as a concurrent edit would """
        if how == 'repointed':
            VideoAsset.objects.filter(pk=pk).update(video_file='other.mp4')
        else:
            VideoAsset.objects.filter(pk=pk).delete()

    @pytest.mark.parametrize('how', ['repointed', 'deleted'])
    def test_changed_asset_is_reported_failed(self, media_storage, how):
        """ The new file is discarded, the original stays and the row is not overwritten """
        folder = media_storage / 'video_file'
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / 'old.avi'
        source.write_bytes(b'original')
        asset = VideoAsset.objects.create(title='Old', status=VideoAsset.VideoStatus.READY)
        VideoAsset.objects.filter(pk=asset.pk).update(video_file='old.avi')
        converted = folder / 'old.mp4'

        def convert_and_change(_source, destination):
            destination.write_bytes(b'converted')
            self.change_row(asset.pk, how)

        output = StringIO()
        with patch('events.management.commands.convert_videoassets.make_web_playable', convert_and_change):
            call_command('convert_videoassets', stdout=output)

        assert '0 converted, 0 already playable, 1 failed' in output.getvalue()
        assert 'changed during conversion' in output.getvalue()
        assert not converted.exists()
        assert source.read_bytes() == b'original'
        if how == 'repointed':
            assert VideoAsset.objects.get(pk=asset.pk).video_file.name == 'other.mp4'
        else:
            assert not VideoAsset.objects.filter(pk=asset.pk).exists()
