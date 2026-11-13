# pylint: disable=redefined-outer-name,unused-argument,too-many-positional-arguments,missing-function-docstring
import importlib.util
import os
from io import BytesIO
from unittest import mock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from django.core.files.base import ContentFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import Resolver404, resolve, reverse
from django.utils.http import http_date, parse_http_date

from arbisoft_sessions_portal import urls as project_urls
from events.factories import EventFactory, EventPresenterFactory, PlaylistFactory, TagFactory, VideoAssetFactory
from events.models import Event, VideoAsset
from events.v1.serializers import EventSerializer, VideoAssetSerializer
from events.v1.streaming import FileRangeIterator

CONTENT = bytes(range(256)) * 8  # 2048 bytes
STREAM_PATH = '/api/v1/events/videoasset/{}/stream/'


def attach_file(asset, content=CONTENT, name='talk.mp4'):
    """ Store ``content`` for ``asset`` without VideoAsset.save(), which would run ffmpeg """
    asset.video_file.save(name, ContentFile(content), save=False)
    VideoAsset.objects.filter(pk=asset.pk).update(video_file=asset.video_file.name)
    return asset


@pytest.fixture
def stream_asset(media_storage):
    """ A video asset whose file really exists in the temporary media storage """
    return attach_file(VideoAssetFactory(event=EventFactory(slug='my-talk')))


@pytest.fixture
def empty_asset(media_storage):
    """ A video asset whose stored file is zero bytes long """
    return attach_file(VideoAssetFactory(event=EventFactory(slug='my-talk')), content=b'')


@pytest.fixture
def opened_handles(stream_asset, monkeypatch):
    """ Every file object the video storage hands out, so tests can prove each one gets closed """
    storage = stream_asset.video_file.storage
    real_open = storage.open
    handles = []

    def tracking_open(*args, **kwargs):
        handles.append(real_open(*args, **kwargs))
        return handles[-1]

    monkeypatch.setattr(storage, 'open', tracking_open)
    return handles


def replace_file_after_open(monkeypatch, asset, content=b'X' * 500):
    """ Make the storage swap a different file over the asset's path right after each real ``open`` """
    storage, path, replaced = asset.video_file.storage, asset.video_file.path, []
    real_open = storage.open

    def open_then_replace(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        with open(f'{path}.new', 'wb') as replacement:
            replacement.write(content)
        os.replace(f'{path}.new', path)
        replaced.append(True)
        return handle

    monkeypatch.setattr(storage, 'open', open_then_replace)
    return replaced


def body(response):
    return b''.join(response.streaming_content)


@pytest.mark.django_db
class TestVideoAssetStream:
    """ The video bytes must only be reachable through an authenticated request """

    url = staticmethod(lambda: reverse('video-asset-stream', args=['my-talk']))

    def test_anonymous_request_is_rejected(self, stream_asset):
        response = APIClient().get(self.url())
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_invalid_token_is_rejected(self, stream_asset):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer not-a-real-token')
        assert client.get(self.url()).status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_full_response(self, user_client, stream_asset):
        response = user_client.get(self.url())
        assert response.status_code == status.HTTP_200_OK
        assert response['Accept-Ranges'] == 'bytes'
        assert response['Content-Type'] == 'video/mp4'
        assert response['Content-Length'] == str(len(CONTENT))
        assert 'no-store' in response['Cache-Control']
        assert body(response) == CONTENT

    @pytest.mark.parametrize('header, served', [
        ('bytes=0-99', (CONTENT[0:100], 'bytes 0-99/2048')),
        ('bytes=100-', (CONTENT[100:], 'bytes 100-2047/2048')),
        ('bytes=-50', (CONTENT[-50:], 'bytes 1998-2047/2048')),
        ('bytes=2000-99999', (CONTENT[2000:], 'bytes 2000-2047/2048')),
    ], ids=['first-100', 'open-ended', 'suffix', 'end-clamped'])
    def test_range_requests(self, user_client, stream_asset, header, served):
        expected, content_range = served
        response = user_client.get(self.url(), HTTP_RANGE=header)
        assert response.status_code == status.HTTP_206_PARTIAL_CONTENT
        assert response['Content-Range'] == content_range
        assert response['Content-Length'] == str(len(expected))
        assert body(response) == expected

    def test_unsatisfiable_range(self, user_client, stream_asset):
        response = user_client.get(self.url(), HTTP_RANGE='bytes=5000-')
        assert response.status_code == status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
        assert response['Content-Range'] == 'bytes */2048'

    @pytest.mark.parametrize('header', ['bytes=0-1,5-6', 'garbage', 'bytes=-'])
    def test_ignored_range_serves_whole_file(self, user_client, stream_asset, header):
        response = user_client.get(self.url(), HTTP_RANGE=header)
        assert response.status_code == status.HTTP_200_OK
        assert body(response) == CONTENT

    def test_stale_if_range_serves_whole_file(self, user_client, stream_asset):
        response = user_client.get(self.url(), HTTP_RANGE='bytes=0-9', HTTP_IF_RANGE='"stale"')
        assert response.status_code == status.HTTP_200_OK
        assert len(body(response)) == len(CONTENT)

    def test_matching_if_range_serves_partial(self, user_client, stream_asset):
        etag = user_client.get(self.url())['ETag']
        response = user_client.get(self.url(), HTTP_RANGE='bytes=0-9', HTTP_IF_RANGE=etag)
        assert response.status_code == status.HTTP_206_PARTIAL_CONTENT

    def test_unknown_slug_is_404(self, user_client, stream_asset):
        response = user_client.get(reverse('video-asset-stream', args=['nope']))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize('method', ['get', 'head'])
    def test_missing_file_is_404(self, user_client, stream_asset, method):
        stream_asset.video_file.storage.delete(stream_asset.video_file.name)
        response = getattr(user_client, method)(self.url())
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert 'Content-Range' not in response

    def test_path_through_a_file_is_404(self, user_client, stream_asset):
        VideoAsset.objects.filter(pk=stream_asset.pk).update(video_file=f'{stream_asset.video_file.name}/inner.mp4')
        assert user_client.get(self.url()).status_code == status.HTTP_404_NOT_FOUND

    def test_event_without_video_file_is_404(self, user_client):
        VideoAssetFactory(event=EventFactory(slug='empty'))
        assert user_client.get(reverse('video-asset-stream', args=['empty'])).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestVideoFileIsNeverARawMediaUrl:
    """ API responses must not leak a directly playable ``/media/`` URL """

    def test_detail_exposes_stream_path(self, user_client, stream_asset):
        response = user_client.get(reverse('video-asset-detail', args=[stream_asset.event.slug]))
        assert response.data['video_file'] == '/api/v1/events/videoasset/my-talk/stream/'
        assert response.data['event']['video_file'] == '/api/v1/events/videoasset/my-talk/stream/'
        assert '/media/' not in response.data['video_file']

    def test_list_exposes_stream_path(self, user_client, stream_asset):
        response = user_client.get(reverse('events-list'))
        assert response.data['results'][0]['video_file'] == '/api/v1/events/videoasset/my-talk/stream/'


@pytest.mark.django_db
class TestVideoAssetStreamEdgeCases:
    """ Error paths and protocol corners of the stream endpoint """

    url = staticmethod(lambda: reverse('video-asset-stream', args=['my-talk']))

    def test_head_has_headers_and_no_body(self, user_client, stream_asset):
        response = user_client.head(self.url())
        assert response.status_code == status.HTTP_200_OK
        assert response['Content-Length'] == str(len(CONTENT))
        assert response['Accept-Ranges'] == 'bytes'
        assert body(response) == b''

    @pytest.mark.parametrize('method, read_body', [('head', False), ('get', False), ('get', True)],
                             ids=['head', 'unread-get', 'read-get'])
    def test_opened_handles_closed_by_response(self, user_client, stream_asset, opened_handles, method, read_body):
        response = getattr(user_client, method)(self.url())
        if read_body:
            assert body(response) == CONTENT
        assert response.status_code == status.HTTP_200_OK
        assert len(opened_handles) == 1
        if method == 'get' and not read_body:
            assert [handle.closed for handle in opened_handles] == [False]
        response.close()
        assert all(handle.closed for handle in opened_handles)

    @pytest.mark.parametrize('header', ['bytes=5000-', 'bytes=-0'])
    def test_unsatisfiable_range_closes_handle(self, user_client, stream_asset, opened_handles, header):
        response = user_client.get(self.url(), HTTP_RANGE=header)
        assert response.status_code == status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
        assert response['Content-Range'] == 'bytes */2048'
        assert len(opened_handles) == 1
        assert opened_handles[0].closed

    @pytest.mark.parametrize('extra, served', [
        ({}, (status.HTTP_200_OK, None, CONTENT)),
        ({'HTTP_RANGE': 'bytes=100-'}, (status.HTTP_206_PARTIAL_CONTENT, 'bytes 100-2047/2048', CONTENT[100:])),
    ], ids=['full', 'ranged'])
    def test_headers_describe_the_opened_file(self, user_client, stream_asset, monkeypatch, extra, served):
        expected_status, content_range, expected = served
        baseline = user_client.get(self.url())
        assert body(baseline) == CONTENT
        replaced = replace_file_after_open(monkeypatch, stream_asset)
        response = user_client.get(self.url(), **extra)
        assert replaced
        assert os.path.getsize(stream_asset.video_file.path) == 500
        assert response.status_code == expected_status
        assert response.get('Content-Range') == content_range
        assert response['Content-Length'] == str(len(expected))
        assert response['ETag'] == baseline['ETag']
        assert response['Last-Modified'] == baseline['Last-Modified']
        assert body(response) == expected

    @pytest.mark.parametrize('failing', ['_build_response', '_parse_range', '_if_range_matches'])
    def test_error_while_building_closes_handle(self, user_client, stream_asset, opened_handles, monkeypatch, failing):
        monkeypatch.setattr(f'events.v1.streaming.{failing}', mock.Mock(side_effect=RuntimeError))
        with pytest.raises(RuntimeError):
            user_client.get(self.url(), HTTP_RANGE='bytes=0-9')
        assert len(opened_handles) == 1
        assert opened_handles[0].closed

    @pytest.mark.parametrize('error', [FileNotFoundError, NotADirectoryError])
    @pytest.mark.parametrize('method', ['get', 'head'])
    def test_open_failure_is_404(self, user_client, stream_asset, monkeypatch, method, error):
        monkeypatch.setattr(stream_asset.video_file.storage, 'open', mock.Mock(side_effect=error))
        response = getattr(user_client, method)(self.url())
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert 'Content-Range' not in response

    def test_file_truncated_mid_stream_underdelivers(self, user_client, stream_asset, caplog):
        response = user_client.get(self.url())
        assert response['Content-Length'] == str(len(CONTENT))
        with open(stream_asset.video_file.path, 'r+b') as stored:
            stored.truncate(100)
        with caplog.at_level('WARNING', logger='asp_api'):
            assert body(response) == CONTENT[:100]
        assert f'ended {len(CONTENT) - 100} bytes before' in caplog.text

    @pytest.mark.parametrize('header', ['bytes=-0', 'bytes=-50', 'bytes=0-'])
    def test_range_on_empty_file_is_416(self, user_client, empty_asset, header):
        response = user_client.get(self.url(), HTTP_RANGE=header)
        assert response.status_code == status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
        assert response['Content-Range'] == 'bytes */0'

    def test_empty_file_without_range_is_200(self, user_client, empty_asset):
        response = user_client.get(self.url())
        assert response.status_code == status.HTTP_200_OK
        assert response['Content-Length'] == '0'
        assert body(response) == b''

    @pytest.mark.parametrize('header', ['bytes=-0', 'bytes=-000'])
    def test_zero_suffix_range_is_416(self, user_client, stream_asset, header):
        response = user_client.get(self.url(), HTTP_RANGE=header)
        assert response.status_code == status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
        assert response['Content-Range'] == 'bytes */2048'

    @pytest.mark.parametrize('header', ['bytes=9-2', 'bytes=5-4'])
    def test_inverted_range_serves_whole_file(self, user_client, stream_asset, header):
        response = user_client.get(self.url(), HTTP_RANGE=header)
        assert response.status_code == status.HTTP_200_OK
        assert 'Content-Range' not in response
        assert response['Content-Length'] == str(len(CONTENT))
        assert body(response) == CONTENT

    def test_matching_if_range_date_serves_partial(self, user_client, stream_asset):
        last_modified = user_client.get(self.url())['Last-Modified']
        response = user_client.get(self.url(), HTTP_RANGE='bytes=0-9', HTTP_IF_RANGE=last_modified)
        assert response.status_code == status.HTTP_206_PARTIAL_CONTENT
        assert response['Content-Range'] == 'bytes 0-9/2048'
        assert body(response) == CONTENT[:10]

    @pytest.mark.parametrize('shift', [-3600, 3600], ids=['older', 'newer'])
    def test_stale_if_range_date_serves_whole_file(self, user_client, stream_asset, shift):
        last_modified = parse_http_date(user_client.get(self.url())['Last-Modified'])
        response = user_client.get(self.url(), HTTP_RANGE='bytes=0-9', HTTP_IF_RANGE=http_date(last_modified + shift))
        assert response.status_code == status.HTTP_200_OK
        assert 'Content-Range' not in response
        assert body(response) == CONTENT

    def test_unparsable_if_range_serves_whole_file(self, user_client, stream_asset):
        response = user_client.get(self.url(), HTTP_RANGE='bytes=0-9', HTTP_IF_RANGE='not a date')
        assert response.status_code == status.HTTP_200_OK
        assert body(response) == CONTENT

    @pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
    def test_write_methods_are_405(self, user_client, stream_asset, method):
        response = getattr(user_client, method)(self.url())
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert 'GET' in response['Allow']

    @pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
    def test_anonymous_write_methods_rejected(self, stream_asset, method):
        response = getattr(APIClient(), method)(self.url())
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @pytest.mark.parametrize('method', ['get', 'head'])
    @pytest.mark.parametrize('extra', [{}, {'HTTP_RANGE': 'bytes=0-9'}], ids=['plain', 'ranged'])
    def test_anonymous_gets_no_file_bytes(self, stream_asset, method, extra):
        response = getattr(APIClient(), method)(self.url(), **extra)
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert not response.streaming
        assert CONTENT[:32] not in response.content
        assert response.get('Content-Length') != str(len(CONTENT))
        assert not {'Content-Range', 'ETag', 'Last-Modified', 'Accept-Ranges'} & set(response.headers)

    @pytest.mark.parametrize('range_header, expected_status', [
        (None, status.HTTP_200_OK),
        ('bytes=0-9', status.HTTP_206_PARTIAL_CONTENT),
    ], ids=['full', 'ranged'])
    @pytest.mark.parametrize('accept', ['application/json', 'text/html', 'text/csv'])
    def test_strict_accept_header_is_not_406(self, user_client, stream_asset, accept, range_header, expected_status):
        extra = {'HTTP_RANGE': range_header} if range_header else {}
        response = user_client.get(self.url(), HTTP_ACCEPT=accept, **extra)
        assert response.status_code == expected_status
        assert response['Content-Type'] == 'video/mp4'

    def test_strict_accept_header_on_404_is_not_406(self, user_client):
        response = user_client.get(reverse('video-asset-stream', args=['nope']), HTTP_ACCEPT='text/csv')
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestPlayableAssetSelection:
    """ The stream and the serializers must agree on which asset of a multi-asset event is playable """

    url = staticmethod(lambda: reverse('video-asset-stream', args=['multi']))

    @pytest.fixture
    def multi_event(self, media_storage):
        """ Assets in pk order: NULL file, empty-string file, playable A, playable B """
        event = EventFactory(slug='multi')
        null_file = VideoAssetFactory(event=event)
        VideoAsset.objects.filter(pk=null_file.pk).update(video_file=None)
        blank_file = VideoAssetFactory(event=event)
        VideoAsset.objects.filter(pk=blank_file.pk).update(video_file='')
        attach_file(VideoAssetFactory(event=event), content=b'A' * 10, name='a.mp4')
        attach_file(VideoAssetFactory(event=event), content=b'B' * 20, name='b.mp4')
        assert VideoAsset.objects.filter(pk=null_file.pk, video_file__isnull=True).exists()
        return event

    def test_stream_serves_lowest_pk_with_file(self, user_client, multi_event):
        response = user_client.get(self.url())
        assert response.status_code == status.HTTP_200_OK
        assert response['Content-Length'] == '10'
        assert body(response) == b'A' * 10

    def test_ranged_stream_uses_same_asset(self, user_client, multi_event):
        response = user_client.get(self.url(), HTTP_RANGE='bytes=2-4')
        assert response.status_code == status.HTTP_206_PARTIAL_CONTENT
        assert response['Content-Range'] == 'bytes 2-4/10'
        assert body(response) == b'AAA'

    def test_list_advertises_stream_for_playable(self, user_client, multi_event):
        results = user_client.get(reverse('events-list')).data['results']
        assert {result['video_file'] for result in results} == {STREAM_PATH.format('multi')}

    @pytest.mark.parametrize('stored', [None, ''], ids=['null', 'blank'])
    def test_no_playable_asset_is_404_and_blank(self, user_client, media_storage, stored):
        event = EventFactory(slug='multi')
        asset = VideoAssetFactory(event=event, video_file=None)
        VideoAsset.objects.filter(pk=asset.pk).update(video_file=stored)
        assert user_client.get(self.url()).status_code == status.HTTP_404_NOT_FOUND
        assert user_client.head(self.url()).status_code == status.HTTP_404_NOT_FOUND
        results = user_client.get(reverse('events-list')).data['results']
        assert [result['video_file'] for result in results] == ['']

    def test_event_without_assets_serializes_blank(self):
        event = EventFactory(slug='bare')
        assert EventSerializer(event).data['video_file'] == ''

    @pytest.mark.parametrize('stored', [None, ''], ids=['null', 'blank'])
    def test_serializer_blank_when_file_empty(self, stored):
        event = EventFactory(slug='bare')
        asset = VideoAssetFactory(event=event, video_file=None)
        VideoAsset.objects.filter(pk=asset.pk).update(video_file=stored)
        assert EventSerializer(event).data['video_file'] == ''

    def test_serializer_stream_path_when_playable(self, media_storage):
        event = EventFactory(slug='bare')
        attach_file(VideoAssetFactory(event=event))
        assert EventSerializer(event).data['video_file'] == STREAM_PATH.format('bare')

    def test_serializer_skips_unplayable_first_asset(self, media_storage):
        event = EventFactory(slug='bare')
        VideoAssetFactory(event=event, video_file=None)
        attach_file(VideoAssetFactory(event=event))
        assert EventSerializer(event).data['video_file'] == STREAM_PATH.format('bare')

    def test_asset_without_event_serializes_blank(self, media_storage):
        asset = attach_file(VideoAssetFactory(event=None))
        data = VideoAssetSerializer(VideoAsset.objects.get(pk=asset.pk)).data
        assert data['video_file'] == ''
        assert data['event'] is None

    def test_fileless_asset_serializer_matches_event(self, media_storage):
        """ An asset with no file still advertises the event's stream while a sibling asset is playable """
        event = EventFactory(slug='multi')
        first = VideoAssetFactory(event=event, video_file=None)
        attach_file(VideoAssetFactory(event=event))
        asset_data = VideoAssetSerializer(VideoAsset.objects.get(pk=first.pk)).data
        assert asset_data['video_file'] == EventSerializer(event).data['video_file']
        assert asset_data['video_file'] == STREAM_PATH.format('multi')


@pytest.mark.django_db
class TestDuplicateSlugStream:
    """
    Slugs are not unique. The stream resolves the asset with ``event_videos``, like the video detail and the view
    count: a video with a file beats one without, then the lowest event pk wins.
    """

    url = staticmethod(lambda: reverse('video-asset-stream', args=['dup']))

    def test_lowest_pk_event_with_file_streams(self, user_client, media_storage):
        """
        The stream is keyed by slug, so a duplicate-slug event B advertises a stream path that serves
        event A's bytes. This is acceptable only because duplicate slugs are treated as a data error
        and a duplicate can never serve its own video.
        """
        attach_file(VideoAssetFactory(event=EventFactory(slug='dup')), content=b'A' * 10, name='a.mp4')
        attach_file(VideoAssetFactory(event=EventFactory(slug='dup')), content=b'B' * 20, name='b.mp4')
        response = user_client.get(self.url())
        assert response.status_code == status.HTTP_200_OK
        assert response['Content-Length'] == '10'
        assert body(response) == b'A' * 10

    def test_event_with_a_file_beats_a_lower_pk_without(self, user_client, media_storage):
        """ The lowest-pk event has nothing to play, so the stream serves the next event's file instead of a 404 """
        VideoAssetFactory(event=EventFactory(slug='dup'), video_file=None)
        attach_file(VideoAssetFactory(event=EventFactory(slug='dup')), content=b'B' * 20, name='b.mp4')
        response = user_client.get(self.url())
        assert response.status_code == status.HTTP_200_OK
        assert body(response) == b'B' * 20

    def test_slug_without_any_file_is_404(self, user_client):
        VideoAssetFactory(event=EventFactory(slug='dup'), video_file=None)
        VideoAssetFactory(event=EventFactory(slug='dup'), video_file=None)
        assert user_client.get(self.url()).status_code == status.HTTP_404_NOT_FOUND
        assert user_client.head(self.url()).status_code == status.HTTP_404_NOT_FOUND

    def test_stream_detail_and_view_count_agree(self, user_client, media_storage):
        """ The three endpoints resolve the same asset, so the player never meets a 404 after a 200 """
        VideoAssetFactory(event=EventFactory(slug='dup'), video_file=None, title='Nothing to play')
        playable = attach_file(
            VideoAssetFactory(event=EventFactory(slug='dup'), title='Playable'), content=b'B' * 20, name='b.mp4'
        )
        detail = user_client.get(reverse('video-asset-detail', args=['dup']))
        counted = user_client.post(reverse('video-asset-increment-view', args=['dup']))
        streamed = user_client.get(self.url())
        assert (detail.status_code, counted.status_code, streamed.status_code) == (200, 200, 200)
        assert detail.data['title'] == 'Playable'
        assert VideoAsset.objects.get(pk=playable.pk).view_count == 1
        assert body(streamed) == b'B' * 20


@pytest.mark.django_db
@pytest.mark.parametrize('stored', [None, ''], ids=['null', 'blank'])
class TestEventWithoutSlug:
    """ An event whose slug is NULL or blank cannot be addressed by the stream route, so it advertises no stream """

    @staticmethod
    def slugless_event(stored):
        event = EventFactory(slug='temporary')
        attach_file(VideoAssetFactory(event=event))
        Event.objects.filter(pk=event.pk).update(slug=stored)
        return Event.objects.get(pk=event.pk)

    def test_list_has_blank_video_file(self, user_client, media_storage, stored):
        event = self.slugless_event(stored)
        response = user_client.get(reverse('events-list'))
        assert response.status_code == status.HTTP_200_OK
        assert [(result['id'], result['slug'], result['video_file']) for result in response.data['results']] == [
            (event.pk, stored, '')
        ]

    def test_recommendations_have_blank_video_file(self, user_client, media_storage, stored):
        tag = TagFactory()
        EventFactory(slug='current').tags.add(tag)
        event = self.slugless_event(stored)
        event.tags.add(tag)
        response = user_client.get(reverse('recommendation', args=['current']))
        assert response.status_code == status.HTTP_200_OK
        assert [(result['id'], result['video_file']) for result in response.data['results']] == [(event.pk, '')]

    def test_serializers_have_blank_video_file(self, media_storage, stored):
        event = self.slugless_event(stored)
        asset_data = VideoAssetSerializer(event.videos.get()).data
        assert EventSerializer(event).data['video_file'] == ''
        assert asset_data['video_file'] == ''
        assert asset_data['event']['video_file'] == ''


class TestFileRangeIterator:
    """ The iterator behind every streamed body: seeks, caps at ``length`` and always releases the handle """

    @pytest.mark.parametrize('start, length', [(0, 2048), (100, 50), (2000, 48), (7, 1)])
    def test_yields_exactly_the_requested_window(self, monkeypatch, start, length):
        monkeypatch.setattr('events.v1.streaming.CHUNK_SIZE', 64)
        chunks = list(FileRangeIterator(BytesIO(CONTENT), start, length))
        assert b''.join(chunks) == CONTENT[start:start + length]
        assert max(len(chunk) for chunk in chunks) <= 64

    def test_length_caps_a_longer_file(self):
        assert b''.join(FileRangeIterator(BytesIO(CONTENT), 10, 5)) == CONTENT[10:15]

    def test_seeks_from_wherever_the_handle_is(self):
        handle = BytesIO(CONTENT)
        handle.seek(1000)
        assert b''.join(FileRangeIterator(handle, 3, 4)) == CONTENT[3:7]

    def test_close_closes_the_handle(self):
        handle = BytesIO(CONTENT)
        FileRangeIterator(handle, 0, 10).close()
        assert handle.closed

    def test_truncated_file_stops_and_warns(self, caplog):
        with caplog.at_level('WARNING', logger='asp_api'):
            data = b''.join(FileRangeIterator(BytesIO(CONTENT[:100]), 40, 500))
        assert data == CONTENT[40:100]
        assert '440 bytes before the advertised Content-Length' in caplog.text

    def test_complete_read_does_not_warn(self, caplog):
        with caplog.at_level('WARNING', logger='asp_api'):
            assert b''.join(FileRangeIterator(BytesIO(CONTENT), 0, 2048)) == CONTENT
        assert not caplog.records


def make_card_events(count, start=0, shared=None):
    """ Create ``count`` events carrying a video, two tags, a playlist and two presenters """
    for number in range(start, start + count):
        event = EventFactory(slug=f'card-{number}')
        VideoAssetFactory(event=event, video_file=None)
        event.tags.add(*TagFactory.create_batch(2))
        event.playlists.add(PlaylistFactory())
        EventPresenterFactory.create_batch(2, event=event)
        if shared:
            event.tags.add(shared)


def count_queries(client, url):
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    return len(captured), response


@pytest.mark.django_db
class TestCardQueryCount:
    """ Serializing event cards must cost the same number of queries regardless of how many events there are """

    def test_events_list_query_count_is_constant(self, user_client):
        make_card_events(2)
        few_queries, few = count_queries(user_client, reverse('events-list'))
        make_card_events(4, start=2)
        many_queries, many = count_queries(user_client, reverse('events-list'))
        assert (len(few.data['results']), len(many.data['results'])) == (2, 6)
        assert many_queries == few_queries

    def test_events_list_cards_carry_related_data(self, user_client):
        make_card_events(3)
        result = user_client.get(reverse('events-list')).data['results'][0]
        assert len(result['tags']) == 2
        assert len(result['playlists']) == 1
        assert len(result['presenters']) == 2
        assert isinstance(result['tags'], list)
        assert isinstance(result['playlists'], list)

    def test_recommendations_query_count_is_constant(self, user_client):
        tag = TagFactory()
        current = EventFactory(slug='current')
        current.tags.add(tag)
        url = reverse('recommendation', args=['current'])
        make_card_events(2, shared=tag)
        few_queries, few = count_queries(user_client, url)
        make_card_events(4, start=2, shared=tag)
        many_queries, many = count_queries(user_client, url)
        assert (len(few.data['results']), len(many.data['results'])) == (2, 6)
        assert many_queries == few_queries

    def test_video_detail_query_count_is_constant(self, user_client, media_storage):
        url = reverse('video-asset-detail', args=['card-0'])
        make_card_events(1)
        few_queries, few = count_queries(user_client, url)
        make_card_events(5, start=1)
        many_queries, _ = count_queries(user_client, url)
        assert len(few.data['event']['presenters']) == 2
        assert many_queries == few_queries


def debug_urlconf(settings):
    """ A private copy of the project urlconf evaluated with ``DEBUG`` on, leaving the real one untouched """
    settings.DEBUG = True
    spec = importlib.util.spec_from_file_location('debug_project_urls', project_urls.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDebugMediaRouting:
    """ Even in DEBUG only thumbnails and captions may be served straight from ``MEDIA_URL`` """

    @pytest.mark.parametrize('path', ['/media/thumbnails/a.jpg', '/media/captions/a.vtt'])
    def test_public_media_routable_in_debug(self, settings, path):
        match = resolve(path, urlconf=debug_urlconf(settings))
        assert match.kwargs['path'] == path.rsplit('/', 1)[1]

    @pytest.mark.parametrize('path', [
        '/media/videos/a.mp4',
        '/media/uploads/a.part',
        '/media/a.mp4',
        '/media/',
        '/media/thumbnailsvideos/a.jpg',
    ])
    def test_private_media_not_routable_in_debug(self, settings, path):
        with pytest.raises(Resolver404):
            resolve(path, urlconf=debug_urlconf(settings))

    @pytest.mark.parametrize('path', ['/media/thumbnails/a.jpg', '/media/captions/a.vtt', '/media/videos/a.mp4'])
    def test_no_media_routes_without_debug(self, path):
        with pytest.raises(Resolver404):
            resolve(path)
