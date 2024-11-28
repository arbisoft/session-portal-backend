from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def __str__(self):
        return self.name

class Event(models.Model):
    EVENT_STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('ARCHIVED', 'Archived')
    ]

    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='events')
    title = models.CharField(max_length=255)
    description = models.TextField()
    event_date = models.DateTimeField()
    event_type = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=EVENT_STATUS_CHOICES)
    workstream_id = models.CharField(max_length=100, blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, related_name='events')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class VideoAsset(models.Model):
    STATUS_CHOICES = [
        ('PROCESSING', 'Processing'),
        ('READY', 'Ready'),
        ('FAILED', 'Failed')
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='videos')
    title = models.CharField(max_length=255)
    s3_key = models.CharField(max_length=255)
    cdn_url = models.URLField()
    duration = models.IntegerField()  # in seconds
    thumbnail_url = models.URLField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    file_size = models.BigIntegerField()  # in bytes
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title
