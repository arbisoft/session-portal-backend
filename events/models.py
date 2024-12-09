from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()

class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)


    def __str__(self):
        return self.name

class Event(models.Model):
    class EventType(models.TextChoices):
        SESSION = "SESSION", _("Session")

    class EventStatus(models.TextChoices):
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
    class VideoStatus(models.TextChoices):
        PROCESSING = "PROCESSING", _("Processing")
        READY = "READY", _("Ready")
        FAILED = "FAILED", _("Failed")


    event = models.ForeignKey(Event, on_delete=models.DO_NOTHING, related_name='videos')
    title = models.CharField(max_length=255)
    cdn_url = models.URLField()
    duration = models.IntegerField()  # in seconds
    thumbnail_url = models.URLField()
    status = models.CharField(max_length=20, choices=VideoStatus.choices)
    file_size = models.BigIntegerField()  # in bytes
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title
