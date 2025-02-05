import ffmpeg

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils.translation import gettext_lazy as _

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
    description = models.TextField()
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
    description = models.TextField()
    event_time = models.DateTimeField()
    event_type = models.CharField(max_length=20, choices=EventType.choices, default=EventType.SESSION)
    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.DRAFT)
    workstream_id = models.CharField(max_length=100, blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, related_name='events')
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

    event = models.ForeignKey(Event, on_delete=models.DO_NOTHING, related_name='videos')
    title = models.CharField(max_length=255)
    video_file = models.FileField(storage=video_storage, null=True, blank=True)
    duration = models.IntegerField(default=0)  # in seconds
    thumbnail = models.ImageField(storage=thumbnail_storage, null=True, blank=True)
    status = models.CharField(max_length=20, choices=VideoStatus.choices)
    file_size = models.BigIntegerField(default=0)  # in bytes
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """ Override save method to extract file size and duration """
        if self.video_file:
            super().save(*args, **kwargs)

            self.file_size = self.video_file.size
            video_path = self.video_file.path
            try:
                video_path = '/app/xyz.mp4'
                metadata = ffmpeg.probe(video_path)
                duration = float(metadata['format']['duration'])
                self.duration = int(duration)  # Convert to seconds
            except ffmpeg._run.Error as e:
                print(f"FFmpeg processing error: {e.stderr.decode() if hasattr(e, 'stderr') else e}")
            except KeyError:
                print("Metadata does not contain 'duration'. Invalid file format.")
            except ValueError:
                print("Invalid duration value, unable to convert to float.")

        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
