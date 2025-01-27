from rest_framework import serializers

from django.contrib.auth import get_user_model

from events.models import Event

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

    class Meta:
        model = Event
        fields = (
            'id', 'title', 'description', 'publisher', 'event_time', 'event_type', 'status', 'workstream_id',
            'is_featured', 'tags'
        )

    @staticmethod
    def get_tags(event):
        """ Get the tags of an event """
        return event.tags.all().values_list('name', flat=True)
