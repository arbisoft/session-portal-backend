import pytest
from faker import Faker
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.urls import reverse

from events.factories import EventFactory, PlaylistFactory, TagFactory, UserFactory, VideoAssetFactory
from events.models import Event, VideoAsset
from events.v1.utils import event_videos

fake = Faker()
User = get_user_model()


@pytest.mark.django_db
class TestEventsAPI:
    """ Test cases for Events APIs """

    def test_list_events(self, user_client):
        """ Test listing all events """
        events = [EventFactory() for _ in range(3)]
        for event in events:
            VideoAssetFactory(event=event)
        response = user_client.get(reverse("events-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3

    def test_list_events_with_and_without_videoasset(self, user_client):
        """ Test that /events/all returns only events with linked VideoAssets """

        # Create 2 events without video assets
        EventFactory.create_batch(2)

        # Create 3 events and attach video assets
        events_with_video = [EventFactory() for _ in range(3)]
        for event in events_with_video:
            VideoAssetFactory(event=event)

        response = user_client.get(reverse("events-list"))  # Replace with actual route name if different

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3

        returned_ids = {e["id"] for e in response.data["results"]}
        expected_ids = {e.id for e in events_with_video}

        assert returned_ids == expected_ids, "Only events with VideoAssets should be returned"

    def test_video_asset_detail(self, user_client):
        """ Test retrieving a video asset detail """
        video_asset = VideoAssetFactory()
        response = user_client.get(reverse("video-asset-detail", args=[video_asset.event.slug]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == video_asset.title
        assert response.data["status"] == VideoAsset.VideoStatus.READY

    def test_increment_video_asset_view_count(self, user_client):
        """ Test that POST to view endpoint increments view_count by 1 """
        video_asset = VideoAssetFactory()
        assert video_asset.view_count == 0
        url = reverse("video-asset-increment-view", args=[video_asset.event.slug])
        response = user_client.post(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["view_count"] == 1
        # Call again — should be 2
        response = user_client.post(url)
        assert response.data["view_count"] == 2

    def test_list_playlists(self, user_client):
        """ Test listing all playlists """
        linked_playlist = PlaylistFactory(name="Used Playlist")
        unused_playlist = PlaylistFactory(name="Unused Playlist")

        event = EventFactory()
        event.playlists.add(linked_playlist)

        response = user_client.get(reverse("playlist-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

        response = user_client.get(reverse("playlist-list"), {'linked_to_events': True})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Used Playlist"

    def test_list_tags(self, user_client):
        """ Test listing all tags """
        used_tag = TagFactory(name="Used Tag")
        unused_tag = TagFactory(name="Unused Tag")

        event = EventFactory()
        event.tags.add(used_tag)

        response = user_client.get(reverse("tag-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

        response = user_client.get(reverse("tag-list"), {'linked_to_events': True})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Used Tag"

    def test_event_recommendations(self, user_client):
        """ Test retrieving event recommendations """
        playlist = PlaylistFactory()
        tag = TagFactory()
        presenter = UserFactory()
        event = EventFactory()
        event.playlists.add(playlist)
        event.tags.add(tag)
        event.presenters.add(presenter)
        event.save()

        # Create one similar event (shares playlist)
        similar_event = EventFactory()
        similar_event.playlists.add(playlist)
        similar_event.save()

        # Create other events with different playlists
        for _ in range(10):
            other_playlist = PlaylistFactory()
            unrelated_event = EventFactory()
            unrelated_event.playlists.add(other_playlist)
            unrelated_event.save()

        response = user_client.get(reverse("recommendation", args=[event.slug]))
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        returned_ids = {e["id"] for e in results}
        assert similar_event.id in returned_ids
        assert event.id not in returned_ids
        # Similar events + 5 latest events
        assert len(results) == 6


def make_playable(*assets):
    """ Give assets a stored file name without running the ffmpeg processing done by VideoAsset.save() """
    VideoAsset.objects.filter(pk__in=[asset.pk for asset in assets]).update(video_file='talk.mp4')


@pytest.mark.django_db
class TestEventVideosOrdering:
    """ Test cases for the lookup shared by the detail and view count endpoints """

    def test_lowest_event_pk_comes_first(self):
        """ With a duplicate slug the older event wins, even when its video has no file """
        older = EventFactory(slug='talk')
        newer = EventFactory(slug='talk')
        newer_asset = VideoAssetFactory(event=newer)
        older_asset = VideoAssetFactory(event=older)
        make_playable(newer_asset)

        assert list(event_videos('talk')) == [older_asset, newer_asset]

    def test_playable_before_unplayable_then_pk(self):
        """ Within an event videos with a file come first, each group by ascending pk """
        event = EventFactory(slug='talk')
        unplayable = VideoAssetFactory(event=event)
        empty_name = VideoAssetFactory(event=event)
        first_playable = VideoAssetFactory(event=event)
        second_playable = VideoAssetFactory(event=event)
        make_playable(second_playable, first_playable)
        VideoAsset.objects.filter(pk=empty_name.pk).update(video_file='')

        assert list(event_videos('talk')) == [first_playable, second_playable, unplayable, empty_name]

    def test_other_slugs_are_excluded(self):
        """ Only videos of the requested slug are returned """
        VideoAssetFactory(event=EventFactory(slug='other'))

        assert not event_videos('talk').exists()


@pytest.mark.django_db
class TestEventFirstVideo:
    """ Test cases for Event.first_video and Event.playable_video """

    @staticmethod
    def loaded(event):
        """ The event as the list and detail endpoints load it, with its videos prefetched """
        return Event.objects.with_card_data().get(pk=event.pk)

    def test_first_video_is_lowest_pk(self):
        """ Without the playable filter the lowest pk wins, with or without a file """
        event = EventFactory(slug='talk')
        unplayable = VideoAssetFactory(event=event)
        playable = VideoAssetFactory(event=event)
        make_playable(playable)

        assert self.loaded(event).first_video() == unplayable

    def test_only_playable_skips_files_less_video(self):
        """ With only_playable the lowest pk among videos that have a file wins """
        event = EventFactory(slug='talk')
        VideoAssetFactory(event=event)
        playable = VideoAssetFactory(event=event)
        make_playable(playable)

        assert self.loaded(event).first_video(only_playable=True) == playable

    def test_playable_video_matches_only_playable(self):
        """ playable_video is first_video(only_playable=True) """
        event = EventFactory(slug='talk')
        VideoAssetFactory(event=event)
        make_playable(VideoAssetFactory(event=event), VideoAssetFactory(event=event))
        loaded = self.loaded(event)

        assert loaded.playable_video() == loaded.first_video(only_playable=True)
        assert loaded.playable_video() is not None

    def test_no_videos_returns_none(self):
        """ An event without a (playable) video has nothing to return """
        event = EventFactory(slug='talk')
        VideoAssetFactory(event=event)
        loaded = self.loaded(event)

        assert loaded.first_video() is not None
        assert loaded.first_video(only_playable=True) is None
        assert loaded.playable_video() is None
        assert self.loaded(EventFactory(slug='empty')).first_video() is None

    def test_python_and_sql_rules_agree(self):
        """ event_videos (SQL) and playable_video (Python) pick the same asset """
        event = EventFactory(slug='talk')
        VideoAssetFactory(event=event)
        make_playable(VideoAssetFactory(event=event), VideoAssetFactory(event=event))

        assert event_videos('talk').first() == self.loaded(event).playable_video()


@pytest.mark.django_db
class TestVideoAssetDetailDuplicateSlugs:
    """ Test cases for the video asset detail endpoint when slugs are not unique """

    def test_duplicate_slug_returns_chosen_asset(self, user_client):
        """ Two events with the same slug answer 200 with the asset the stream endpoint serves """
        older = EventFactory(slug='talk')
        newer = EventFactory(slug='talk')
        VideoAssetFactory(event=older, title='No file')
        newer_playable = VideoAssetFactory(event=newer, title='Newer playable')
        make_playable(newer_playable)

        response = user_client.get(reverse("video-asset-detail", args=['talk']))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == "No file"
        assert response.data["event"]["id"] == older.id

    def test_playable_asset_preferred_in_event(self, user_client):
        """ Within one event the video with a file is described """
        event = EventFactory(slug='talk')
        VideoAssetFactory(event=event, title='No file')
        make_playable(VideoAssetFactory(event=event, title='Playable'))

        response = user_client.get(reverse("video-asset-detail", args=['talk']))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == "Playable"

    def test_unknown_slug_returns_404(self, user_client):
        """ A slug without videos is not found """
        response = user_client.get(reverse("video-asset-detail", args=['missing']))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_anonymous_is_rejected(self):
        """ The detail endpoint requires authentication """
        response = APIClient().get(reverse("video-asset-detail", args=['talk']))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
