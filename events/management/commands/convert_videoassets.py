import logging
import os
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Case, F, Value, When

from events.models import VideoAsset
from events.v1.transcoding import TranscodeError, make_web_playable, needs_conversion, probe_duration

logger = logging.getLogger("asp_api")


class Command(BaseCommand):
    """
    Convert videos stored before uploads were converted, so every asset is a browser-playable MP4.

    Run one instance at a time: the free output name is picked before a conversion that can take hours and is not
    reserved, so two overlapping runs could choose the same name.
    """

    help = 'Convert stored videos that are not H.264/AAC MP4 files (AVI, WebM, ProRes, HEVC...) into ones that play'

    def add_arguments(self, parser):
        parser.add_argument('asset_ids', nargs='*', type=int, help='Only these video asset IDs (default: all)')
        parser.add_argument(
            '--dry-run', action='store_true', help='List what would be converted without changing anything'
        )

    def handle(self, *args, **options):
        queryset = VideoAsset.objects.exclude(video_file='').exclude(video_file__isnull=True).order_by('pk')
        if options['asset_ids']:
            queryset = queryset.filter(pk__in=options['asset_ids'])

        converted = skipped = failed = 0
        for asset in queryset:
            source = Path(asset.video_file.path)
            if not source.exists():
                self.stdout.write(self.style.WARNING(f'#{asset.pk} {asset.title}: file is missing, skipped'))
                failed += 1
            elif not needs_conversion(source):
                skipped += 1
            elif options['dry_run']:
                self.stdout.write(f'#{asset.pk} {asset.title}: would convert {source.name}')
                converted += 1
            elif self._convert(asset, source):
                converted += 1
            else:
                failed += 1

        verb = 'would be converted' if options['dry_run'] else 'converted'
        self.stdout.write(f'{converted} {verb}, {skipped} already playable, {failed} failed')

    def _convert(self, asset, source: Path) -> bool:
        """
        Write the MP4 under a free name in the video storage, point the asset at it, and only then delete the original.

        The name is the original's with an ``.mp4`` extension, made unique by the storage when it is taken. That keeps
        another asset's ``talk.mp4`` safe from a ``talk.avi`` conversion, and an HEVC ``talk.mp4`` is converted to a new
        file instead of being replaced in place, so a failed conversion never touches the original.

        Uses ``update()`` because ``VideoAsset.save()`` would write back every column as it was before a conversion
        that can take hours, losing the views counted meanwhile. The converted file is probed here instead: an asset
        whose original could not be probed (``duration`` 0, ``FAILED``) gets its duration and becomes ``READY``, so it
        can be attached to an event. The update only matches while the asset still points at the original file; if it
        was deleted or repointed during the conversion, the new file is discarded and the original is kept.
        """
        storage = asset.video_file.storage
        original_name = asset.video_file.name
        storage_name = storage.get_available_name(f'{os.path.splitext(asset.video_file.name)[0]}.mp4')
        destination = Path(storage.path(storage_name))
        try:
            make_web_playable(source, destination)
        except TranscodeError:
            logger.exception('convert_videoassets_failed asset=%s', asset.pk)
            self.stdout.write(self.style.ERROR(f'#{asset.pk} {asset.title}: conversion failed, left as it was'))
            return False

        changes = {'video_file': storage_name, 'file_size': destination.stat().st_size}
        duration = probe_duration(destination)
        if duration:
            changes['duration'] = duration
            changes['status'] = Case(
                When(status=VideoAsset.VideoStatus.FAILED, then=Value(VideoAsset.VideoStatus.READY)),
                default=F('status'),
            )
        updated = VideoAsset.objects.filter(pk=asset.pk, video_file=original_name).update(**changes)
        if not updated:
            destination.unlink(missing_ok=True)
            logger.error('convert_videoassets_asset_changed asset=%s file=%s', asset.pk, source.name)
            self.stdout.write(self.style.ERROR(f'#{asset.pk} {asset.title}: changed during conversion, left as it was'))
            return False
        try:
            source.unlink(missing_ok=True)
        except OSError:
            logger.exception('convert_videoassets_original_remove_failed asset=%s file=%s', asset.pk, source.name)
        self.stdout.write(self.style.SUCCESS(f'#{asset.pk} {asset.title}: converted'))
        return True
