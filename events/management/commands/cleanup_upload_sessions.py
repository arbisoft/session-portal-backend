from django.core.management.base import BaseCommand

from events.v1.uploads import cleanup_sessions


class Command(BaseCommand):
    help = 'Expire abandoned resumable upload sessions, restart stalled finalizations and delete leftover files'

    def handle(self, *args, **options):
        summary = cleanup_sessions()
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")
