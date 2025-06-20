import logging
import os

import ffmpeg

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import File
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger("asp_api")

User = get_user_model()
video_storage = FileSystemStorage(
    location=settings.MEDIA_ROOT / 'videos',
    base_url=settings.MEDIA_URL + 'videos/'
)
thumbnail_storage = FileSystemStorage(
    location=settings.MEDIA_ROOT / 'thumbnails',
    base_url=settings.MEDIA_URL + 'thumbnails/'
)


class Tag(models.Model):
    """ Model to store tags for events """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Playlist(models.Model):
    """ Model to store playlists for events """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Event(models.Model):
    """ Model to store events """
    class EventType(models.TextChoices):
        """ Enum for event types """
        SESSION = "SESSION", _("Session")

    class EventStatus(models.TextChoices):
        """ Enum for event status """
        DRAFT = "DRAFT", _("Draft")
        PUBLISHED = "PUBLISHED", _("Published")
        ARCHIVED = "ARCHIVED", _("Archived")

    creator = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name='events')
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, blank=True, null=True)
    description = models.TextField()
    event_time = models.DateTimeField()
    event_type = models.CharField(max_length=20, choices=EventType.choices, default=EventType.SESSION)
    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.DRAFT)
    workstream_id = models.CharField(max_length=100, blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, related_name='events', blank=True)
    playlists = models.ManyToManyField(Playlist, related_name='events', blank=True)
    presenters = models.ManyToManyField(User, through='EventPresenter', related_name='events_presented')
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class VideoAsset(models.Model):
    """ Model to store video assets """
    class VideoStatus(models.TextChoices):
        """ Enum for video status """
        PROCESSING = "PROCESSING", _("Processing")
        READY = "READY", _("Ready")
        FAILED = "FAILED", _("Failed")

    event = models.ForeignKey(Event, on_delete=models.DO_NOTHING, related_name='videos', null=True, blank=True)
    title = models.CharField(max_length=255)
    video_file = models.FileField(storage=video_storage, null=True, blank=True)
    duration = models.IntegerField(default=0)  # in seconds
    thumbnail = models.ImageField(storage=thumbnail_storage, null=True, blank=True)
    status = models.CharField(max_length=20, choices=VideoStatus.choices)
    file_size = models.BigIntegerField(default=0)  # in bytes
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """ Override save method to extract file size, duration and thumbnail """
        if self.video_file:
            super().save(*args, **kwargs)
            self.file_size = self.video_file.size
            video_path = self.video_file.path

            try:
                metadata = ffmpeg.probe(video_path)
                duration = float(metadata['format'].get('duration', 0))
                self.duration = int(duration)  # Convert to seconds

                if not self.thumbnail:
                    thumbnail_filename = f"{os.path.splitext(os.path.basename(video_path))[0]}_thumb.jpg"
                    thumbnail_path = os.path.join(os.path.dirname(video_path), thumbnail_filename)

                    # Take a frame at 20% of the video duration for the thumbnail
                    time_offset = max(1, int(self.duration * 0.2))

                    # Use ffmpeg to extract a frame as the thumbnail
                    (
                        ffmpeg
                        .input(video_path, ss=time_offset)
                        .output(thumbnail_path, vframes=1)
                        .overwrite_output()
                        .run(quiet=True)
                    )

                    # Save the thumbnail to the model
                    with open(thumbnail_path, 'rb') as thumb_file:
                        self.thumbnail.save(thumbnail_filename, File(thumb_file), save=False)

                    # Clean up the temporary file
                    os.remove(thumbnail_path)

            except ffmpeg.Error as e:
                logger.error("FFmpeg processing error: %s", e.stderr.decode() if hasattr(e, 'stderr') else e)
            except KeyError:
                logger.error("Metadata does not contain 'duration'. Invalid file format.")
            except ValueError:
                logger.error("Invalid duration value, unable to convert to float.")

        super().save(*args, **kwargs)

    def file_size_mb(self):
        """
        Returns the file size in MB, formatted to two decimal places.
        """
        if self.file_size is None:
            return ""
        return f"{self.file_size / (1024 * 1024):.2f}"

    file_size_mb.short_description = "File Size (MB)"

    def duration_hh_mm_ss(self):
        """
        Converts duration in seconds to hh:mm:ss format.
        """
        if self.duration is None:
            return ""

        seconds = int(self.duration)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        remaining_seconds = seconds % 60

        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"

    duration_hh_mm_ss.short_description = "Duration"

    def __str__(self):
        return self.title


class EventPresenter(models.Model):
    """ Model to store presenters for an event """
    event = models.ForeignKey(Event, on_delete=models.DO_NOTHING)
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING)

    class Meta:
        unique_together = ('event', 'user')

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"
