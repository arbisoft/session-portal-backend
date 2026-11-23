import re
from datetime import timedelta

import pytest

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from events.factories import EventFactory, EventPresenterFactory, UserFactory, VideoAssetFactory
from events.forms import EventPresenterForm, VideoAssetForm

User = get_user_model()


@pytest.mark.django_db
class TestVideoAssetForm:
    """Class to test the VideoAssetForm form"""
    def test_video_asset_form_valid_with_file(self):
        """
        Test VideoAssetForm is valid when a video file is provided
        """
        event = EventFactory()
        video_file = SimpleUploadedFile(
            name='test_video.mp4',
            content=b'fake video content',
            content_type='video/mp4'
        )

        form_data = {
            'title': 'Test Video',
            'video_file': video_file,
            'google_drive_link': ''
        }

        form = VideoAssetForm(data=form_data, files={'video_file': video_file})
        form.instance.event = event

        assert form.is_valid(), form.errors

    def test_video_asset_form_valid_with_google_drive_link(self):
        """
        Test VideoAssetForm is valid when a Google Drive link is provided
        """
        event = EventFactory()

        form_data = {
            'title': 'Test Video',
            'video_file': None,
            'google_drive_link': 'https://drive.google.com/file/d/testfileid/view'
        }

        form = VideoAssetForm(data=form_data)
        form.instance.event = event

        assert form.is_valid(), form.errors

    def test_video_asset_form_invalid_no_input(self):
        """
        Test VideoAssetForm is invalid when no video file or Google Drive link is provided
        """
        event = EventFactory()

        form_data = {
            'title': 'Test Video',
            'video_file': None,
            'google_drive_link': ''
        }

        form = VideoAssetForm(data=form_data)
        form.instance.event = event

        assert not form.is_valid()
        assert 'You must provide either a video file or a Google Drive link.' in form.errors['__all__']

    def test_video_asset_form_invalid_both_inputs(self):
        """
        Test VideoAssetForm is invalid when both video file and Google Drive link are provided
        """
        event = EventFactory()

        # Create a mock video file
        video_file = SimpleUploadedFile(
            name='test_video.mp4',
            content=b'fake video content',
            content_type='video/mp4'
        )

        form_data = {
            'title': 'Test Video',
            'video_file': video_file,
            'google_drive_link': 'https://drive.google.com/file/d/testfileid/view'
        }

        form = VideoAssetForm(data=form_data, files={'video_file': video_file})
        form.instance.event = event

        assert not form.is_valid()
        assert 'Please provide only one: either a video file or a Google Drive link.' in form.errors['__all__']


@pytest.mark.django_db
class TestEventPresenterForm:
    """Class to test the EventPresenterForm form"""
    def test_event_presenter_form_valid(self):
        """
        Test EventPresenterForm is valid with a user
        """
        user = UserFactory()
        event = EventFactory(creator=user)

        form_data = {
            'user': user.id,
            'event': event.id
        }

        form = EventPresenterForm(data=form_data)

        assert form.is_valid(), form.errors

    def test_event_presenter_form_invalid_no_user(self):
        """
        Test EventPresenterForm is invalid when no user is provided
        """
        event = EventFactory()

        form_data = {
            'user': None,
            'event': event.id
        }

        form = EventPresenterForm(data=form_data)

        assert not form.is_valid()
        assert 'This field is required.' in form.errors['user']

    def test_event_presenter_form_queryset_order(self):
        """
        Test that user queryset is ordered by first_name and last_name
        """
        UserFactory(username='user1', first_name='Alice', last_name='Zebra')
        UserFactory(username='user2', first_name='Bob', last_name='Yard')
        UserFactory(username='user3', first_name='Charlie', last_name='Xavier')

        form = EventPresenterForm()
        users = list(form.fields['user'].queryset)

        expected_first_names = ['Alice', 'Bob', 'Charlie']
        actual_first_names = [user.first_name for user in users]

        assert actual_first_names == expected_first_names, f"Expected {expected_first_names}, got {actual_first_names}"


@pytest.mark.django_db
class TestEventAdminChangelist:
    """Class to test the Event admin changelist"""
    @pytest.fixture
    def superuser_client(self):
        """ A Django test client logged in as a superuser """
        client = Client()
        client.force_login(UserFactory(is_staff=True, is_superuser=True))
        return client

    @staticmethod
    def row_html(content, event):
        """ The changelist table row that links to the given event """
        change_url = reverse('admin:events_event_change', args=[event.pk])
        rows = re.split(r'<tr[\s>]', content)
        return next(row for row in rows if f'href="{change_url}"' in row)

    def test_changelist_renders_views_and_presenters(self, superuser_client):
        """ The changelist shows each event's summed video views and its presenters' full names """
        event = EventFactory()
        VideoAssetFactory(event=event, view_count=3)
        VideoAssetFactory(event=event, view_count=4)
        EventPresenterFactory(event=event, user=UserFactory(first_name='Alice', last_name='Zebra'))
        EventPresenterFactory(event=event, user=UserFactory(first_name='Bob', last_name='Yard'))
        empty_event = EventFactory()

        response = superuser_client.get(reverse('admin:events_event_changelist'))

        assert response.status_code == 200
        content = response.content.decode()
        row = self.row_html(content, event)
        assert '<td class="field-get_view_count">7</td>' in row
        assert 'Alice Zebra' in row
        assert 'Bob Yard' in row
        assert '<td class="field-get_view_count">0</td>' in self.row_html(content, empty_event)

    def test_views_column_sorts_by_total_views(self, superuser_client):
        """ Sorting by the Views column orders events by their summed video views """
        low = EventFactory()
        VideoAssetFactory(event=low, view_count=2)
        high = EventFactory()
        VideoAssetFactory(event=high, view_count=5)
        VideoAssetFactory(event=high, view_count=6)
        none = EventFactory()
        url = reverse('admin:events_event_changelist')
        column = superuser_client.get(url).context['cl'].list_display.index('get_view_count')

        ascending = superuser_client.get(url, {'o': column})
        descending = superuser_client.get(url, {'o': -column})

        assert [row.pk for row in ascending.context['cl'].result_list] == [none.pk, low.pk, high.pk]
        assert [row.pk for row in descending.context['cl'].result_list] == [high.pk, low.pk, none.pk]

    def test_presenters_do_not_add_queries_per_event(self, superuser_client):
        """
        Listing more events with presenters does not run more queries (presenters are prefetched).
        The first request is a warm-up for session and permission caches so the counts are comparable.
        """
        url = reverse('admin:events_event_changelist')
        for _ in range(2):
            EventPresenterFactory(event=EventFactory())
        superuser_client.get(url)

        with CaptureQueriesContext(connection) as few_events:
            superuser_client.get(url)
        for _ in range(3):
            EventPresenterFactory(event=EventFactory())
        with CaptureQueriesContext(connection) as many_events:
            superuser_client.get(url)

        assert len(many_events) == len(few_events)

    def test_default_sort_is_newest_first(self, superuser_client):
        """ Events are listed by event time, newest first """
        now = timezone.now()
        old = EventFactory(event_time=now - timedelta(days=10))
        new = EventFactory(event_time=now + timedelta(days=10))
        mid = EventFactory(event_time=now)

        response = superuser_client.get(reverse('admin:events_event_changelist'))

        assert [row.pk for row in response.context['cl'].result_list] == [new.pk, mid.pk, old.pk]
