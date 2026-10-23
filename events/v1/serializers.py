import base64
import binascii
import os

from rest_framework import serializers

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from events.models import Event, EventPresenter, Playlist, Tag, UploadSession, VideoAsset
from events.v1.uploads import clean_display_filename, confirmed_offset, validate_video_extension

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
        validate_video_extension(value.name)
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


class UploadSessionCreateSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """ Validates the request that starts a resumable upload """
    filename = serializers.CharField(max_length=255)
    file_size = serializers.IntegerField(min_value=1)
    checksum_sha256 = serializers.RegexField(r'^[0-9a-fA-F]{64}$', required=False, allow_blank=True, default='')
    client_key = serializers.RegexField(r'^[A-Za-z0-9_-]{8,64}$', required=False, allow_blank=True, default='')

    def validate_filename(self, value):
        """ Keep a display-only name and require a supported video extension """
        return validate_video_extension(clean_display_filename(value))

    def validate_file_size(self, value):
        """ Reject files above the configured upload limit """
        if value > settings.RESUMABLE_UPLOAD_MAX_FILE_BYTES:
            raise serializers.ValidationError(
                f"File is too large. The maximum size is {settings.RESUMABLE_UPLOAD_MAX_FILE_BYTES} bytes."
            )
        return value

    def validate_checksum_sha256(self, value):
        """ Normalize to lower case so it compares with hashlib digests """
        return value.lower()


class UploadChunkHeadersSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """ Validates the headers of a chunk request. The chunk bytes themselves are streamed, never parsed """
    offset = serializers.IntegerField(min_value=0)
    content_length = serializers.IntegerField(min_value=1)
    checksum = serializers.CharField(required=False, allow_blank=True, default='')

    @classmethod
    def from_request(cls, request):
        """ Build the serializer from the ``Upload-Offset``, ``Content-Length`` and ``Upload-Checksum`` headers """
        return cls(data={
            'offset': request.headers.get('Upload-Offset'),
            'content_length': request.META.get('CONTENT_LENGTH') or None,
            'checksum': request.headers.get('Upload-Checksum', ''),
        })

    def validate_checksum(self, value):
        """ Accept the tus form ``sha256 <base64 digest>`` and return the digest as hex """
        if not value:
            return ''
        algorithm, _, encoded = value.partition(' ')
        try:
            digest = base64.b64decode(encoded.strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise serializers.ValidationError('Upload-Checksum must be "sha256 <base64 digest>".') from exc
        if algorithm.lower() != 'sha256' or len(digest) != 32:
            raise serializers.ValidationError('Upload-Checksum must be "sha256 <base64 digest>".')
        return digest.hex()


class UploadSessionSerializer(serializers.ModelSerializer):
    """ Representation of an upload session. ``offset`` is the confirmed, disk-reconciled resume position """
    offset = serializers.SerializerMethodField()
    video_asset_id = serializers.IntegerField(read_only=True)
    upload_status = serializers.CharField(source='status', read_only=True)
    chunk_size = serializers.SerializerMethodField()
    max_chunk_size = serializers.SerializerMethodField()

    class Meta:
        model = UploadSession
        fields = (
            'id', 'filename', 'file_size', 'offset', 'upload_status', 'error_code', 'video_asset_id', 'expires_at',
            'chunk_size', 'max_chunk_size',
        )
        read_only_fields = fields

    @staticmethod
    def get_offset(session) -> int:
        """ Committed bytes the client does not need to send again """
        return confirmed_offset(session)

    @staticmethod
    def get_chunk_size(session) -> int:  # pylint: disable=unused-argument
        """ Chunk size the client should use """
        return settings.RESUMABLE_UPLOAD_CHUNK_BYTES

    @staticmethod
    def get_max_chunk_size(session) -> int:  # pylint: disable=unused-argument
        """ Largest chunk the server accepts """
        return settings.RESUMABLE_UPLOAD_MAX_CHUNK_BYTES
