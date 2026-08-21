import os

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
            'id', 'title', 'slug', 'description', 'publisher', 'event_time',
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
            'title', 'video_file', 'duration', 'thumbnail', 'status', 'file_size', 'view_count', 'event', 'captions_file'
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


class VideoAssetCreateSerializer(serializers.ModelSerializer):
    """ Serializer for creating a VideoAsset via file upload """
    video_file = serializers.FileField(required=True)

    class Meta:
        model = VideoAsset
        fields = ('id', 'title', 'video_file', 'status')
        read_only_fields = ('id', 'title', 'status')

    def validate_video_file(self, value):
        allowed = {"mp4", "mov", "avi", "webm"}
        ext = os.path.splitext(value.name)[1].lower().lstrip(".")
        if ext not in allowed:
            raise serializers.ValidationError(
                f"Unsupported file type '.{ext}'. Allowed formats: {', '.join(sorted(allowed))}."
            )
        return value

    def create(self, validated_data):
        filename = validated_data['video_file'].name
        title = os.path.splitext(os.path.basename(filename))[0]
        return VideoAsset.objects.create(
            title=title,
            video_file=validated_data['video_file'],
            status=VideoAsset.VideoStatus.PROCESSING,
        )


class EventCreateSerializer(serializers.ModelSerializer):
    """ Serializer for creating an Event with all related data """
    presenter_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, default=list
    )
    playlists = serializers.PrimaryKeyRelatedField(
        queryset=Playlist.objects.all(), many=True, required=False
    )
    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, required=False
    )
    video_asset_id = serializers.IntegerField(write_only=True)
    thumbnail = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Event
        fields = (
            'title', 'description', 'event_time', 'playlists', 'tags',
            'presenter_ids', 'video_asset_id', 'thumbnail',
        )

    def create(self, validated_data):
        presenter_ids = validated_data.pop('presenter_ids', [])
        playlists = validated_data.pop('playlists', [])
        tags = validated_data.pop('tags', [])
        video_asset_id = validated_data.pop('video_asset_id')
        thumbnail = validated_data.pop('thumbnail', None)

        event = Event.objects.create(
            creator=self.context['request'].user,
            event_type=Event.EventType.SESSION,
            status=Event.EventStatus.PUBLISHED,
            **validated_data,
        )

        if playlists:
            event.playlists.set(playlists)

        if tags:
            event.tags.set(tags)

        for user_id in presenter_ids:
            EventPresenter.objects.get_or_create(event=event, user_id=user_id)

        video_asset = VideoAsset.objects.filter(id=video_asset_id).first()
        if video_asset:
            video_asset.event = event
            if thumbnail:
                video_asset.thumbnail = thumbnail
            video_asset.save(update_fields=['event', 'thumbnail'] if thumbnail else ['event'])

        return event

    def to_representation(self, instance):
        return EventSerializer(instance, context=self.context).data
