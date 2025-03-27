import pytest

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from events.factories import EventFactory, UserFactory
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
