import logging
from datetime import timedelta

from celery.result import AsyncResult

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from events.models import VideoAsset

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check status of video assets and their associated tasks'

    def add_arguments(self, parser):
        parser.add_argument('asset_ids', nargs='*', type=int, help='Specific video asset IDs to check')
        parser.add_argument(
            '--all',
            action='store_true',
            help='Check all video assets'
        )
        parser.add_argument(
            '--recent',
            type=int,
            default=0,
            help='Check video assets created in the last N hours'
        )
        parser.add_argument(
            '--processing',
            action='store_true',
            help='Only show processing or failed assets'
        )

    def handle(self, *args, **options):
        asset_ids = options['asset_ids']
        check_all = options['all']
        recent_hours = options['recent']
        only_processing = options['processing']

        if not asset_ids and not check_all and not recent_hours:
            self.stdout.write(self.style.ERROR(
                "Please specify either specific asset IDs, --all flag, or --recent hours"
            ))
            return

        video_assets = self._get_video_assets(asset_ids, check_all, recent_hours, only_processing)

        if not video_assets:
            self.stdout.write(self.style.WARNING("No video assets found matching the criteria"))
            return

        self._display_assets_status(video_assets)

    def _get_video_assets(self, asset_ids, check_all, recent_hours, only_processing):
        queryset = VideoAsset.objects.all()

        if asset_ids:
            queryset = queryset.filter(id__in=asset_ids)
        elif recent_hours > 0:
            time_threshold = timezone.now() - timedelta(hours=recent_hours)
            queryset = queryset.filter(created__gte=time_threshold)
        # If check_all is false and no other filter is applied, return empty
        elif not check_all:
            return []

        if only_processing:
            queryset = queryset.filter(
                status__in=[
                    VideoAsset.VideoStatus.PROCESSING,
                    VideoAsset.VideoStatus.FAILED
                ]
            )

        return queryset.order_by('-created')

    def _display_assets_status(self, video_assets):
        self.stdout.write(self.style.SUCCESS(f"\n=== Video Assets Status ({video_assets.count()} assets) ===\n"))

        status_counts = {}

        for asset in video_assets:

            if asset.status not in status_counts:
                status_counts[asset.status] = 0
            status_counts[asset.status] += 1

            event_info = f"'{asset.event.title}'" if asset.event else "No associated event"
            created_date = asset.created.strftime("%Y-%m-%d %H:%M:%S") if hasattr(asset, 'created') else "Unknown"

            self.stdout.write(f"Video Asset ID: {asset.id}")
            self.stdout.write(f"  Title: {asset.title}")
            self.stdout.write(f"  Event: {event_info}")
            self.stdout.write(f"  Created: {created_date}")
            self.stdout.write(f"  Status: {asset.status}")

            if hasattr(asset, 'video_file') and asset.video_file:
                self.stdout.write(f"  File: {asset.video_file}")

            if hasattr(asset, 'thumbnail') and asset.thumbnail:
                self.stdout.write(f"  Thumbnail: {asset.thumbnail}")

            self.stdout.write("")

        self.stdout.write(self.style.SUCCESS("=== Status Summary ==="))
        for status, count in status_counts.items():
            status_style = self._get_status_style(status)
            self.stdout.write(status_style(f"{status}: {count}"))

    def _get_status_style(self, status):
        status_styles = {
            VideoAsset.VideoStatus.PROCESSING: self.style.WARNING,
            VideoAsset.VideoStatus.FAILED: self.style.ERROR,
            VideoAsset.VideoStatus.READY: self.style.SUCCESS,
        }
        return status_styles.get(status, self.style.NOTICE)
