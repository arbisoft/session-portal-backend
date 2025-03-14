from rest_framework import serializers

from django.contrib.auth import get_user_model

from events.models import Event, Tag, VideoAsset
from users.v1.serializers import UserSerializer

user_model = get_user_model()


class PublisherSerializer(serializers.ModelSerializer):
    """ Serializer for the publisher field in the Event model """

    class Meta:
        model = user_model
        fields = ('id', 'first_name', 'last_name')


class EventSerializer(serializers.ModelSerializer):
    """ Serializer for the Event model """

    publisher = PublisherSerializer(source='creator')
    tags = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    video_duration = serializers.SerializerMethodField()
    presenters = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = (
            'id', 'title', 'description', 'publisher', 'event_time',
            'event_type', 'status', 'workstream_id', 'is_featured', 'tags',
            'thumbnail', 'video_duration', 'presenters'
        )

    @staticmethod
    def get_tags(event):
        """ Get the tags of an event """
        return event.tags.all().values_list('name', flat=True)

    @staticmethod
    def get_thumbnail(event):
        """ Get thumbnail of an event if available """
        video = event.videos.first()
        return video.thumbnail.url if video and video.thumbnail else ''

    @staticmethod
    def get_video_duration(event):
        """ Get duration of video if available """
        video = event.videos.first()
        return video.duration if video and video.duration else None

    @staticmethod
    def get_presenters(obj):
        """ Fetch presenters' full details (user id, first_name, last_name, email)"""
        return UserSerializer(
            [ep.user for ep in obj.presenters.all()], many=True
        ).data


class VideoAssetSerializer(serializers.ModelSerializer):
    """ Serializer for the VideoAsset model """

    event = EventSerializer()

    class Meta:
        model = VideoAsset
        fields = (
            'title', 'video_file', 'duration', 'thumbnail', 'status', 'file_size', 'event'
        )


class TagListSerializer(serializers.ModelSerializer):
    """ Serializer for Tag List View"""
    class Meta:
        model = Tag
        fields = ('id', 'name')
