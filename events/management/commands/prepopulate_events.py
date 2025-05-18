import csv
import logging
from datetime import datetime

from celery.result import AsyncResult

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from events.models import Event, EventPresenter, Playlist, Tag, VideoAsset
from events.tasks import download_google_drive_video

User = get_user_model()
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Import events from a CSV file with optional dry-run.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the CSV file.')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without modifying the database.'
        )
        parser.add_argument(
            '--skip-video-download',
            action='store_true',
            help='Skip downloading videos and just create the assets.'
        )
        parser.add_argument(
            '--creator',
            type=str,
            help='Username of the creator to set for all imported events'
        )

    def handle(self, *args, **options):
        file_path = options['csv_file']
        dry_run = options['dry_run']
        skip_video_download = options['skip_video_download']
        creator_username = options.get('creator')

        self.check_celery_configuration()

        creator = None
        if creator_username:
            creator = self._get_creator(creator_username)

        stats = {
            'new_users': set(),
            'existing_users': set(),
            'new_tags': set(),
            'existing_tags': set(),
            'new_playlists': set(),
            'existing_playlists': set(),
            'new_events': set(),
            'existing_events': set(),
            'new_video_assets': set(),
            'video_assets_status': {},
            'parsed_events': []
        }

        try:
            with open(file_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row_num, row in enumerate(reader, start=1):
                    self._process_row(row, row_num, stats, dry_run, skip_video_download, creator)

            self._show_summary(stats, dry_run)

        except Exception as e:
            logger.error(f"Error processing CSV: {str(e)}")
            self.stdout.write(self.style.ERROR(f"Error processing CSV: {str(e)}"))
            raise

    def _get_creator(self, username):
        creator = User.objects.filter(username=username).first()
        if creator:
            self.stdout.write(f"Using {username} as creator for all events")
        else:
            self.stdout.write(self.style.ERROR(f"Creator with username '{username}' not found"))
        return creator

    def _process_row(self, row, row_num, stats, dry_run, skip_video_download, override_creator=None):
        title = row.get("Title", "").strip()
        description = row.get("Details", "").strip()
        trainer_names = [t.strip() for t in row.get("Trainer", "").split(",") if t.strip()]
        publish_date = row.get("Publish Date", "").strip()
        gdrive_link = row.get("Link", "").strip()
        playlist_names = [p.strip() for p in row.get("Playlist", "").split(",") if p.strip()]
        tag_names = [t.strip() for t in row.get("Tags", "").split(",") if t.strip()]

        self.stdout.write(f"Processing row {row_num}: {title}")

        presenters = self._parse_presenters(trainer_names, row_num, stats, dry_run)
        playlists = self._parse_playlists(playlist_names, stats, dry_run)
        tags = self._parse_tags(tag_names, stats, dry_run)
        event_time = self._parse_date(publish_date, row_num)

        # Check if event already exists
        existing_event = None
        if event_time:
            existing_event = Event.objects.filter(title=title, event_time=event_time).first()

        if existing_event:
            stats['existing_events'].add(f"{title} ({publish_date})")
            self.stdout.write(self.style.WARNING(f"[Row {row_num}] Event already exists: {title} ({publish_date})"))
            return

        if dry_run:
            stats['new_events'].add(f"{title} ({publish_date})")
            if gdrive_link:
                stats['new_video_assets'].add(f"{title} ({publish_date})")
            self._record_dry_run_event(title, description, trainer_names, tag_names, playlist_names,
                                       publish_date, gdrive_link, stats)
        else:
            event, video_asset = self._create_event(title, description, presenters, tags, playlists,
                                                    event_time, gdrive_link, skip_video_download, override_creator)
            stats['new_events'].add(f"{title} ({publish_date})")

            if video_asset:
                stats['new_video_assets'].add(f"{title} ({publish_date})")
                stats['video_assets_status'][f"{title} ({publish_date})"] = {
                    'id': video_asset.id,
                    'status': video_asset.status,
                    'link': gdrive_link
                }

    def _parse_presenters(self, trainer_names, row_num, stats, dry_run):
        presenters = []

        for name in trainer_names:
            parts = name.strip().split()
            if not parts:
                self.stdout.write(self.style.WARNING(f"[Row {row_num}] Skipping empty name"))
                continue

            if len(parts) == 1:
                first_name = parts[0]
                last_name = ""
                username = parts[0].lower()
            else:
                first_name = parts[0]
                last_name = " ".join(parts[1:])
                username = "_".join(parts).lower()

            user = User.objects.filter(first_name=first_name, last_name=last_name).first()

            if user:
                stats['existing_users'].add(user.username)
            else:
                stats['new_users'].add(username)
                if not dry_run:
                    user = User.objects.create_user(
                        username=username,
                        first_name=first_name,
                        last_name=last_name
                    )

            if user:
                presenters.append(user)

        return presenters

    def _parse_playlists(self, playlist_names, stats, dry_run):
        playlists = []

        for name in playlist_names:
            playlist = Playlist.objects.filter(name=name).first()
            if playlist:
                stats['existing_playlists'].add(name)
            else:
                stats['new_playlists'].add(name)
                if not dry_run:
                    playlist = Playlist.objects.create(name=name)
            playlists.append(playlist)

        return playlists

    def _parse_tags(self, tag_names, stats, dry_run):
        tags = []

        for name in tag_names:
            tag = Tag.objects.filter(name=name).first()
            if tag:
                stats['existing_tags'].add(name)
            else:
                stats['new_tags'].add(name)
                if not dry_run:
                    tag = Tag.objects.create(name=name)
            tags.append(tag)

        return tags

    def _parse_date(self, publish_date, row_num):
        event_time = None
        try:
            if publish_date:
                event_time = datetime.strptime(publish_date, "%m/%d/%Y")
        except ValueError:
            self.stdout.write(self.style.WARNING(f"[Row {row_num}] Invalid date format: {publish_date}"))

        return event_time

    def _record_dry_run_event(self, title, description, presenters, tags, playlists, publish_date, gdrive_link, stats):
        stats['parsed_events'].append({
            "title": title,
            "description": description[:30] + "..." if len(description) > 30 else description,
            "presenters": presenters,
            "tags": tags,
            "playlists": playlists,
            "event_time": publish_date,
            "link": gdrive_link
        })

    def _create_event(self, title, description, presenters, tags, playlists,
                      event_time, gdrive_link, skip_video_download, override_creator=None):
        event = Event.objects.create(
            title=title,
            description=description,
            creator=override_creator or (presenters[0] if presenters else None),
            event_time=event_time,
            event_type=Event.EventType.SESSION,
            status=Event.EventStatus.PUBLISHED,
            is_featured=False
        )

        for tag in tags:
            if tag:
                event.tags.add(tag)

        for playlist in playlists:
            if playlist:
                event.playlists.add(playlist)

        for user in presenters:
            EventPresenter.objects.get_or_create(event=event, user=user)

        video_asset = None
        if gdrive_link:
            video_asset = self._process_video(event, title, gdrive_link, skip_video_download)

        return event, video_asset

    def _process_video(self, event, title, gdrive_link, skip_video_download):
        video_asset = VideoAsset.objects.create(
            event=event,
            title=title,
            status=VideoAsset.VideoStatus.PROCESSING,
        )

        if not skip_video_download:
            try:
                self.stdout.write(f"Starting download for VideoAsset ID: {video_asset.id}")
                task = download_google_drive_video.apply_async(
                    args=[video_asset.id, gdrive_link],
                    retry=True,
                    retry_policy={
                        'max_retries': 3,
                        'interval_start': 0,
                        'interval_step': 0.2,
                        'interval_max': 0.5,
                    }
                )
                self.stdout.write(f"Video download task started for {video_asset.id}. Task ID: {task.id}")

                task_status = AsyncResult(task.id).status
                self.stdout.write(f"Task status: {task_status}")

            except Exception as e:
                logger.error(f"Failed to start download task: {str(e)}")
                self.stdout.write(self.style.ERROR(f"Failed to start download task: {str(e)}"))
                video_asset.status = VideoAsset.VideoStatus.FAILED
                video_asset.save()
        else:
            self.stdout.write(f"Skipping video download for VideoAsset ID: {video_asset.id}")

        return video_asset

    def _show_stat_summary(self, label, items, indent=4):
        count = len(items)
        padding = " " * indent

        self.stdout.write(f"{label}: {count}")

        if count > 0:
            for item in items:
                self.stdout.write(f"{padding}- {item}")
        self.stdout.write("\n")

    def _show_summary(self, stats, dry_run):
        if dry_run and stats['parsed_events']:
            self._show_dry_run_summary(stats['parsed_events'])

        self.stdout.write(self.style.SUCCESS("\n=== Import Summary ==="))

        sections = [
            ("New Events", stats['new_events']),
            ("Existing Events (Skipped)", stats['existing_events']),
            ("New Video Assets", stats['new_video_assets']),
            ("New Presenters", stats['new_users']),
            ("Existing Presenters", stats['existing_users']),
            ("New Tags", stats['new_tags']),
            ("Existing Tags", stats['existing_tags']),
            ("New Playlists", stats['new_playlists']),
            ("Existing Playlists", stats['existing_playlists']),
        ]

        for label, items in sections:
            self._show_stat_summary(label, items)

        # Show video asset statuses if not in dry run mode
        if not dry_run and stats['video_assets_status']:
            self._show_video_assets_status(stats['video_assets_status'])

        if dry_run:
            self.stdout.write(self.style.WARNING("\nNote: No database changes were made (dry-run mode)."))

    def _show_video_assets_status(self, video_assets_status):
        self.stdout.write(self.style.SUCCESS("\n=== Video Assets Status ==="))
        for event_name, asset_info in video_assets_status.items():
            self.stdout.write(f"  - {event_name}:")
            self.stdout.write(f"      ID: {asset_info['id']}")
            self.stdout.write(f"      Status: {asset_info['status']}")
            self.stdout.write(f"      Video Link: {asset_info['link']}")

            # Check current task status if available
            task_result = self._check_video_task_status(asset_info['id'])
            if task_result:
                self.stdout.write(f"      Task Status: {task_result}")
        self.stdout.write("\n")

        self.stdout.write(self.style.NOTICE(
            "Note: To check video processing status later, run the following command:\n"
            "python manage.py check_videoasset_status [video_asset_id]"
        ))

    def _check_video_task_status(self, video_asset_id):
        try:
            # Try to get the most recent task for this video asset
            video_asset = VideoAsset.objects.get(id=video_asset_id)
            return video_asset.status
        except Exception as e:
            logger.error(f"Error checking video asset {video_asset_id} status: {str(e)}")
            return "Error checking status"

    def _show_dry_run_summary(self, parsed_events):
        self.stdout.write(self.style.NOTICE(f"\n== DRY RUN SUMMARY =="))
        self.stdout.write(f"\nParsed {len(parsed_events)} events:")
        for i, event in enumerate(parsed_events, start=1):
            self.stdout.write(f"  {i}. '{event['title']}'")
            self.stdout.write(f"     - Tags: {', '.join(event['tags'])}")
            self.stdout.write(f"     - Playlists: {', '.join(event['playlists'])}")
            self.stdout.write(f"     - Presenters: {', '.join(event['presenters'])}")
            self.stdout.write(f"     - Publish Date: {event['event_time']}")
            self.stdout.write(f"     - Link: {event['link']}\n")

    def check_celery_configuration(self):
        try:
            broker_url = getattr(settings, 'CELERY_BROKER_URL', None) or getattr(settings, 'BROKER_URL', None)
            if not broker_url:
                self.stdout.write(self.style.WARNING("CELERY_BROKER_URL not found in settings!"))

            if not hasattr(download_google_drive_video, 'name'):
                self.stdout.write(self.style.WARNING("Task may not be properly registered. Check task definition."))
            else:
                self.stdout.write(f"Task registered as: {download_google_drive_video.name}")

            from celery import current_app
            self.stdout.write(f"Celery app configured: {current_app.main}")

        except ImportError:
            self.stdout.write(self.style.ERROR("Celery not properly installed!"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error checking Celery configuration: {str(e)}"))
