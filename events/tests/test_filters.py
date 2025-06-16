from datetime import datetime, timezone

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.urls import reverse

# pylint: disable=duplicate-code
from events.factories import (
    EventFactory,
    EventPresenterFactory,
    PlaylistFactory,
    TagFactory,
    UserFactory,
    VideoAssetFactory,
)

User = get_user_model()


@pytest.mark.django_db
class TestEventFilters:
    """ Test cases for event filters """
    @pytest.fixture
    def api_client(self):
        """ Returns an authenticated instance of APIClient """
        client = APIClient()
        user = UserFactory()
        client.force_authenticate(user=user)
        return client

    def _create_event_with_video(self, **kwargs):
        event = EventFactory(**kwargs)
        VideoAssetFactory(event=event)
        return event

    def test_events_search_filter_by_title(self, api_client):
        """ Test filtering events by search term in title """
        self._create_event_with_video(title="Python Conference 2024")
        self._create_event_with_video(title="Machine Learning Summit")

        response = api_client.get(reverse("events-list"), {'search': 'Python'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Python Conference 2024"

    def test_events_search_filter_by_description(self, api_client):
        """ Test filtering events by search term in description """
        self._create_event_with_video(title="Tech Event 1", description="Python programming techniques")
        self._create_event_with_video(title="Tech Event 2", description="Machine learning advancements")

        response = api_client.get(reverse("events-list"), {'search': 'programming'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Tech Event 1"

    def test_events_tag_filter(self, api_client):
        """ Test filtering events by tag """
        python_tag = TagFactory(name="Python")
        ml_tag = TagFactory(name="Machine Learning")

        event1 = self._create_event_with_video(title="Python Workshop")
        event1.tags.add(python_tag)

        event2 = self._create_event_with_video(title="ML Conference")
        event2.tags.add(ml_tag)

        response = api_client.get(reverse("events-list"), {'tag': 'Python'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Python Workshop"

    def test_events_playlist_filter(self, api_client):
        """ Test filtering events by playlist """
        tech_playlist = PlaylistFactory(name="Tech Talks")
        data_science_playlist = PlaylistFactory(name="Data Science")

        event1 = self._create_event_with_video(title="Python Event")
        event1.playlists.add(tech_playlist)

        event2 = self._create_event_with_video(title="Data Science Workshop")
        event2.playlists.add(data_science_playlist)

        response = api_client.get(reverse("events-list"), {'playlist': 'Tech Talks'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Python Event"

    def test_events_ordering_by_event_type(self, api_client):
        """ Test ordering events by event type """
        self._create_event_with_video(title="Conference A", event_type="conference")
        self._create_event_with_video(title="Webinar B", event_type="webinar")
        self._create_event_with_video(title="Workshop C", event_type="workshop")

        # Order events by event type ascending
        response = api_client.get(reverse("events-list"), {'ordering': 'event_type'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3
        assert response.data["results"][0]["title"] == "Conference A"

        # Order events by event type descending
        response = api_client.get(reverse("events-list"), {'ordering': '-event_type'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3
        assert response.data["results"][0]["title"] == "Workshop C"

    def test_events_ordering_by_featured(self, api_client):
        """ Test ordering events by featured status """
        self._create_event_with_video(title="Featured Event 1", is_featured=True)
        self._create_event_with_video(title="Non-Featured Event", is_featured=False)
        self._create_event_with_video(title="Featured Event 2", is_featured=True)

        # Order events by featured status ascending
        response = api_client.get(reverse("events-list"), {'ordering': 'is_featured'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3
        assert response.data["results"][0]["title"] == "Non-Featured Event"

        # Order events by featured status descending
        response = api_client.get(reverse("events-list"), {'ordering': '-is_featured'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3
        assert response.data["results"][0]["title"] != "Non-Featured Event"

    def test_events_search_filter_fuzzy_matching_title(self, api_client):
        """ Test fuzzy matching in title search """
        self._create_event_with_video(title="All-Hands Meeting 2024")
        self._create_event_with_video(title="Machine Learning Summit")

        response = api_client.get(reverse("events-list"), {'search': 'All Hands'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "All-Hands Meeting 2024"

    def test_events_search_filter_fuzzy_matching_description(self, api_client):
        """ Test fuzzy matching in description search """
        self._create_event_with_video(title="Tech Event", description="Learn about Python programming")
        self._create_event_with_video(title="Other Event", description="Data science basics")

        response = api_client.get(reverse("events-list"), {'search': 'Python'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Tech Event"

    def test_events_search_filter_by_playlist_name(self, api_client):
        """ Test filtering events by search term matching playlist name """
        demo_playlist = PlaylistFactory(name="Demo Hour")
        tech_playlist = PlaylistFactory(name="Tech Talks")

        event1 = self._create_event_with_video(title="Weekly Demo Session", description="Demo of new features")
        event1.playlists.add(demo_playlist)

        event2 = self._create_event_with_video(title="Architecture Discussion", description="Tech stack overview")
        event2.playlists.add(tech_playlist)

        response = api_client.get(reverse("events-list"), {'search': 'Demo'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Weekly Demo Session"

    def test_events_search_filter_by_presenter_name(self, api_client):
        """ Test filtering events by presenter name """
        presenter_user = UserFactory(first_name="Alice", last_name="Johnson")
        other_user = UserFactory(first_name="Bob", last_name="Wilson")

        event1 = self._create_event_with_video(title="Python Workshop")
        event2 = self._create_event_with_video(title="Data Science Talk")

        EventPresenterFactory(event=event1, user=presenter_user)
        EventPresenterFactory(event=event2, user=other_user)

        response = api_client.get(reverse("events-list"), {'search': 'Alice'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Python Workshop"

        response = api_client.get(reverse("events-list"), {'search': 'Johnson'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Python Workshop"

    def test_events_search_multiple_presenters(self, api_client):
        """ Test event with multiple presenters """
        presenter1 = UserFactory(first_name="Alice", last_name="Johnson")
        presenter2 = UserFactory(first_name="Bob", last_name="Smith")
        other_presenter = UserFactory(first_name="Carol", last_name="Davis")

        event1 = self._create_event_with_video(title="Team Presentation")
        event2 = self._create_event_with_video(title="Solo Talk")

        EventPresenterFactory(event=event1, user=presenter1)
        EventPresenterFactory(event=event1, user=presenter2)

        EventPresenterFactory(event=event2, user=other_presenter)

        response = api_client.get(reverse("events-list"), {'search': 'Alice'})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Team Presentation"

        response = api_client.get(reverse("events-list"), {'search': 'Bob'})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Team Presentation"

        response = api_client.get(reverse("events-list"), {'search': 'Carol'})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Solo Talk"

    def test_events_search_filter_by_tag_name(self, api_client):
        """ Test filtering events by search term matching tag name """
        python_tag = TagFactory(name="Python")
        javascript_tag = TagFactory(name="JavaScript")

        event1 = self._create_event_with_video(title="Backend Development")
        event1.tags.add(python_tag)

        event2 = self._create_event_with_video(title="Frontend Development")
        event2.tags.add(javascript_tag)

        response = api_client.get(reverse("events-list"), {'search': 'Python'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Backend Development"

    def test_events_search_no_results(self, api_client):
        """ Test search with no matching results """
        self._create_event_with_video(title="Python Conference")
        self._create_event_with_video(title="Machine Learning Summit")

        response = api_client.get(reverse("events-list"), {'search': 'NonExistentTerm'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    def test_events_search_ordering_by_event_time(self, api_client):
        """ Test that search results are ordered by event_time (newest first) """
        # pylint: disable=unused-variable
        old_event = self._create_event_with_video(
            title="Python Old Event",
            event_time=datetime(2024, 1, 1, tzinfo=timezone.utc)
        )
        new_event = self._create_event_with_video(
            title="Python New Event",
            event_time=datetime(2024, 12, 1, tzinfo=timezone.utc)
        )
        middle_event = self._create_event_with_video(
            title="Python Middle Event",
            event_time=datetime(2024, 6, 1, tzinfo=timezone.utc)
        )

        response = api_client.get(reverse("events-list"), {'search': 'Python'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3

        assert response.data["results"][0]["title"] == "Python New Event"
        assert response.data["results"][1]["title"] == "Python Middle Event"
        assert response.data["results"][2]["title"] == "Python Old Event"

    def test_events_search_multiple_criteria_match(self, api_client):
        """ Test event matching multiple search criteria """
        python_tag = TagFactory(name="Python")
        demo_playlist = PlaylistFactory(name="Demo Hour")

        event = self._create_event_with_video(
            title="Python Programming Demo",
            description="Advanced Python techniques"
        )
        event.tags.add(python_tag)
        event.playlists.add(demo_playlist)

        response = api_client.get(reverse("events-list"), {'search': 'Python'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Python Programming Demo"
