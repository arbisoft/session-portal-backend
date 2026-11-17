import logging
import os
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from events.models import VideoAsset, unguessable_upload_name

logger = logging.getLogger("asp_api")

# 32 hex digits (new names) or the dashed form (resumable uploads are stored as ``<session uuid>.mp4``)
UUID_NAME = re.compile(r'^([0-9a-f]{32}|[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12})\.[a-z0-9]+$')
FIELDS = ('video_file', 'thumbnail')


class Command(BaseCommand):
    """
    Rename stored videos and thumbnails that predate random file names (``video_280.mp4``, ``All_Hands_2026.mov``).

    The old names are guessable, and the old URLs stop working once renamed. Each file is renamed first and the row is
    updated second; if the update fails the file is renamed back, and if that also fails it is logged and reported.
    Files already named by UUID are left alone. Re-running is safe. The row update only matches the name read at the
    start, so a row changed in between is left alone, but do not run this command alongside ``convert_videoassets``.
    """

    help = 'Give existing video and thumbnail files unguessable UUID names and update the database rows'

    def add_arguments(self, parser):
        parser.add_argument('asset_ids', nargs='*', type=int, help='Only these video asset IDs (default: all)')
        parser.add_argument('--dry-run', action='store_true', help='List the renames without changing anything')

    def handle(self, *args, **options):
        queryset = VideoAsset.objects.order_by('pk')
        if options['asset_ids']:
            queryset = queryset.filter(pk__in=options['asset_ids'])

        renamed = skipped = failed = 0
        for asset in queryset:
            for field_name in FIELDS:
                outcome = self._rename(asset, field_name, options['dry_run'])
                renamed += outcome == 'renamed'
                skipped += outcome == 'skipped'
                failed += outcome == 'failed'

        verb = 'would be renamed' if options['dry_run'] else 'renamed'
        self.stdout.write(f'{renamed} {verb}, {skipped} already unguessable or empty, {failed} failed')

    def _rename(self, asset: VideoAsset, field_name: str, dry_run: bool) -> str:
        """ Rename one file of one asset, returning ``renamed``, ``skipped`` or ``failed`` """
        field_file = getattr(asset, field_name)
        if not field_file or UUID_NAME.match(os.path.basename(field_file.name)):
            return 'skipped'

        source = Path(field_file.path)
        if not source.exists():
            self.stdout.write(self.style.WARNING(f'#{asset.pk} {field_name}: {field_file.name} is missing, skipped'))
            return 'failed'

        old_name = field_file.name
        new_name = os.path.join(os.path.dirname(old_name), unguessable_upload_name(asset, old_name))
        target = Path(field_file.storage.path(new_name))
        if dry_run:
            self.stdout.write(f'#{asset.pk} {field_name}: would rename {old_name}')
            return 'renamed'

        try:
            os.rename(source, target)
        except OSError:
            logger.exception('rename_media_failed asset=%s field=%s', asset.pk, field_name)
            return 'failed'
        try:
            # update() skips VideoAsset.save(), which would probe the file and regenerate the thumbnail.
            matched = VideoAsset.objects.filter(pk=asset.pk, **{field_name: old_name}).update(**{field_name: new_name})
        except Exception:
            logger.exception('rename_media_db_failed asset=%s field=%s', asset.pk, field_name)
            matched = 0
        if not matched:
            logger.warning('rename_media_row_changed asset=%s field=%s', asset.pk, field_name)
            self._rollback(asset, field_name, source, target)
            return 'failed'
        self.stdout.write(f'#{asset.pk} {field_name}: {old_name} -> {new_name}')
        return 'renamed'

    def _rollback(self, asset: VideoAsset, field_name: str, source: Path, target: Path) -> bool:
        """ Move a renamed file back; a failure is logged and reported so the file can be moved back by hand """
        try:
            os.rename(target, source)
        except OSError:
            logger.exception('rename_media_rollback_failed asset=%s source=%s target=%s', asset.pk, source, target)
            self.stdout.write(self.style.ERROR(
                f'#{asset.pk} {field_name}: rollback failed, file is at {target}, move it back to {source}'
            ))
            return False
        return True
