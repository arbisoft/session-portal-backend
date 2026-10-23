import os

from rest_framework import serializers

from django.contrib.auth import get_user_model
from django.db import transaction

from events.models import Event, EventPresenter, Playlist, Tag, VideoAsset

user_model = get_user_model()

VIDEO_ASSET_ASSIGNED_ERROR = 'This video asset is already assigned to an event.'


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
            'title', 'video_file', 'duration', 'thumbnail', 'status', 'file_size', 'view_count', 'event',
            'captions_file',
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
        """ Ensure the uploaded file has a supported video extension """
        allowed = {"mp4", "mov", "avi", "webm"}
        ext = os.path.splitext(value.name)[1].lower().lstrip(".")
        if ext not in allowed:
            raise serializers.ValidationError(
                f"Unsupported file type '.{ext}'. Allowed formats: {', '.join(sorted(allowed))}."
            )
        return value

    def create(self, validated_data):
        """
        Create the asset and mark it READY or FAILED.

        VideoAsset.save() probes the file and extracts the thumbnail synchronously, logging ffmpeg failures instead
        of raising, which leaves the duration at 0. The status is written with update() so it is not processed twice.
        """
        filename = validated_data['video_file'].name
        title = os.path.splitext(os.path.basename(filename))[0]

        video_asset = VideoAsset.objects.create(
            title=title,
            video_file=validated_data['video_file'],
            status=VideoAsset.VideoStatus.PROCESSING,
        )
        video_asset.status = VideoAsset.VideoStatus.READY if video_asset.duration > 0 else VideoAsset.VideoStatus.FAILED
        VideoAsset.objects.filter(pk=video_asset.pk).update(status=video_asset.status)
        return video_asset


class EventCreateSerializer(serializers.ModelSerializer):
    """ Serializer for creating an Event with all related data """
    presenter_ids = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=user_model.objects.all()),
        write_only=True,
        required=False,
        default=list,
    )
    playlists = serializers.PrimaryKeyRelatedField(
        queryset=Playlist.objects.all(), many=True, required=False
    )
    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, required=False
    )
    video_asset_id = serializers.PrimaryKeyRelatedField(
        queryset=VideoAsset.objects.all(), source='video_asset', write_only=True
    )
    thumbnail = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Event
        fields = (
            'title', 'description', 'event_time', 'playlists', 'tags',
            'presenter_ids', 'video_asset_id', 'thumbnail',
        )

    def validate_video_asset_id(self, value):
        """ Ensure the video is processed and not already assigned to another event """
        if value.event_id is not None:
            raise serializers.ValidationError(VIDEO_ASSET_ASSIGNED_ERROR)
        if value.status != VideoAsset.VideoStatus.READY:
            raise serializers.ValidationError('This video asset is not ready to be published.')
        return value

    @transaction.atomic
    def create(self, validated_data):
        """
        Create the event and attach the video asset to it.

        The asset row is locked and re-checked so concurrent requests cannot both claim it. It is attached with
        update() because VideoAsset.save() would probe the video and regenerate its thumbnail again.
        """
        presenters = validated_data.pop('presenter_ids', [])
        playlists = validated_data.pop('playlists', [])
        tags = validated_data.pop('tags', [])
        video_asset = validated_data.pop('video_asset')
        thumbnail = validated_data.pop('thumbnail', None)

        video_asset = VideoAsset.objects.select_for_update().filter(pk=video_asset.pk, event__isnull=True).first()
        if video_asset is None:
            raise serializers.ValidationError({'video_asset_id': VIDEO_ASSET_ASSIGNED_ERROR})

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

        EventPresenter.objects.bulk_create(
            [EventPresenter(event=event, user=user) for user in dict.fromkeys(presenters)]
        )

        asset_changes = {'event': event}
        if thumbnail:
            video_asset.thumbnail.save(thumbnail.name, thumbnail, save=False)
            asset_changes['thumbnail'] = video_asset.thumbnail.name
        VideoAsset.objects.filter(pk=video_asset.pk).update(**asset_changes)

        return event

    def to_representation(self, instance):
        return EventSerializer(instance, context=self.context).data
