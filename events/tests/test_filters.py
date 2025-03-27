import pytest
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.urls import reverse

from events.factories import EventFactory, PlaylistFactory, TagFactory, UserFactory

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

    def test_events_search_filter_by_title(self, api_client):
        """ Test filtering events by search term in title """
        EventFactory(title="Python Conference 2024")
        EventFactory(title="Machine Learning Summit")

        response = api_client.get(reverse("events-list"), {'search': 'Python'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Python Conference 2024"

    def test_events_search_filter_by_description(self, api_client):
        """ Test filtering events by search term in description """
        EventFactory(title="Tech Event 1", description="Python programming techniques")
        EventFactory(title="Tech Event 2", description="Machine learning advancements")

        response = api_client.get(reverse("events-list"), {'search': 'programming'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Tech Event 1"

    def test_events_search_filter_by_creator_name(self, api_client):
        """ Test filtering events by creator's first or last name """
        creator1 = UserFactory(first_name="John", last_name="Doe")
        creator2 = UserFactory(first_name="Jane", last_name="Smith")

        EventFactory(title="Event 1", creator=creator1)
        EventFactory(title="Event 2", creator=creator2)

        response = api_client.get(reverse("events-list"), {'search': 'John'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Event 1"

    def test_events_tag_filter(self, api_client):
        """ Test filtering events by tag """
        python_tag = TagFactory(name="Python")
        ml_tag = TagFactory(name="Machine Learning")

        event1 = EventFactory(title="Python Workshop")
        event1.tags.add(python_tag)

        event2 = EventFactory(title="ML Conference")
        event2.tags.add(ml_tag)

        response = api_client.get(reverse("events-list"), {'tag': 'Python'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Python Workshop"

    def test_events_playlist_filter(self, api_client):
        """ Test filtering events by playlist """
        tech_playlist = PlaylistFactory(name="Tech Talks")
        data_science_playlist = PlaylistFactory(name="Data Science")

        event1 = EventFactory(title="Python Event")
        event1.playlists.add(tech_playlist)

        event2 = EventFactory(title="Data Science Workshop")
        event2.playlists.add(data_science_playlist)

        response = api_client.get(reverse("events-list"), {'playlist': 'Tech Talks'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Python Event"

    def test_events_ordering_by_event_type(self, api_client):
        """ Test ordering events by event type """
        EventFactory(title="Conference A", event_type="conference")
        EventFactory(title="Webinar B", event_type="webinar")
        EventFactory(title="Workshop C", event_type="workshop")

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
        EventFactory(title="Featured Event 1", is_featured=True)
        EventFactory(title="Non-Featured Event", is_featured=False)
        EventFactory(title="Featured Event 2", is_featured=True)

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
