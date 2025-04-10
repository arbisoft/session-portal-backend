from rest_framework import serializers

from django.contrib.auth import get_user_model

from events.models import Event, EventPresenter, Playlist, Tag, VideoAsset

user_model = get_user_model()


class PublisherSerializer(serializers.ModelSerializer):
    """ Serializer for the publisher field in the Event model """

    class Meta:
        model = user_model
        fields = ('id', 'first_name', 'last_name')


class EventPresenterSerializer(serializers.ModelSerializer):
    """ Serializer for the EventPresenter model """
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name')
    user_id = serializers.IntegerField(source='user.id')
    email = serializers.EmailField(source='user.email')

    class Meta:
        model = EventPresenter
        fields = ('user_id', 'first_name', 'last_name', 'email')


class EventSerializer(serializers.ModelSerializer):
    """ Serializer for the Event model """

    publisher = PublisherSerializer(source='creator')
    tags = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    video_file = serializers.SerializerMethodField()
    video_duration = serializers.SerializerMethodField()
    presenters = serializers.SerializerMethodField()
    playlists = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = (
            'id', 'title', 'description', 'publisher', 'event_time',
            'event_type', 'status', 'is_featured', 'tags',
            'thumbnail', 'video_duration', 'presenters', 'playlists',
            'video_file'
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
    def get_video_file(event):
        """ Get video file of an event if available """
        video = event.videos.first()
        return video.video_file.url if video and video.video_file else ''

    @staticmethod
    def get_video_duration(event):
        """ Get duration of video if available """
        video = event.videos.first()
        return video.duration if video and video.duration else None

    @staticmethod
    def get_presenters(event):
        """ Get presenters of an event """
        event_presenters = EventPresenter.objects.filter(event=event).select_related('user')
        return EventPresenterSerializer(event_presenters, many=True).data

    @staticmethod
    def get_playlists(event):
        """ Get the playlists of an event """
        return event.playlists.all().values_list('name', flat=True)


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


class PlaylistListSerializer(serializers.ModelSerializer):
    """ Serializer for Playlist List View"""
    class Meta:
        model = Playlist
        fields = ('id', 'name')
