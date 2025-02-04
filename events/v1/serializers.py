from rest_framework import serializers

from django.contrib.auth import get_user_model

from events.models import Event, Tag

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

    class Meta:
        model = Event
        fields = (
            'id', 'title', 'description', 'publisher', 'event_time',
            'event_type', 'status', 'workstream_id', 'is_featured', 'tags',
            'thumbnail'
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


class TagListSerializer(serializers.ModelSerializer):
    """ Serializer for Tag List View"""
    class Meta:
        model = Tag
        fields = ('id', 'name')
