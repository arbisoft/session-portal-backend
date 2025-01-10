from rest_framework import serializers
from events.models import Event
from django.contrib.auth import get_user_model

user_model = get_user_model()

class PublisherSerializer(serializers.ModelSerializer):

    class Meta:
        model = user_model
        fields = ('id', 'first_name', 'last_name')


class EventSerializer(serializers.ModelSerializer):

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
        return event.tags.all().values_list('name', flat=True)
