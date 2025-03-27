import pytest

from django.contrib.auth import get_user_model

from users.factories import UserFactory
from users.forms import CustomUserCreationForm

User = get_user_model()


@pytest.mark.django_db
class TestCustomUserCreationForm:
    """ Test cases for CustomUserCreationForm """
    def test_valid_form_with_password(self, faker):
        """
        Test creating a user with a valid password
        """
        form_data = {
            'username': faker.user_name(),
            'email': faker.email(),
            'first_name': faker.first_name(),
            'last_name': faker.last_name(),
            'password1': 'StrongPassword123!',
            'password2': 'StrongPassword123!'
            }

        form = CustomUserCreationForm(data=form_data)

        assert form.is_valid(), form.errors
        user = form.save()

        assert user.username == form_data['username']
        assert user.email == form_data['email']
        assert user.first_name == form_data['first_name']
        assert user.last_name == form_data['last_name']
        assert user.check_password('StrongPassword123!')
        assert User.objects.count() == 1

    def test_valid_form_without_password(self, faker):
        """
        Test creating a user without a password
        (should set an unusable password)
        """
        form_data = {
            'username': faker.user_name(),
            'email': faker.email(),
            'first_name': faker.first_name(),
            'last_name': faker.last_name(),
            'password1': '',
            'password2': ''
            }

        form = CustomUserCreationForm(data=form_data)

        assert form.is_valid(), form.errors
        user = form.save()

        assert user.username == form_data['username']
        assert user.email == form_data['email']
        assert user.has_usable_password() is False
        assert User.objects.count() == 1

    def test_invalid_form_mismatched_passwords(self, faker):
        """
        Test form validation when passwords do not match
        """
        form_data = {
            'username': faker.user_name(),
            'email': faker.email(),
            'first_name': faker.first_name(),
            'last_name': faker.last_name(),
            'password1': 'StrongPassword123!',
            'password2': 'DifferentPassword456!'
        }

        form = CustomUserCreationForm(data=form_data)

        assert not form.is_valid()
        assert 'Passwords do not match.' in form.errors.get('__all__', [])

    def test_form_invalid_without_data(self):
        """
        Test form validation with empty data
        """
        form = CustomUserCreationForm(data={})

        assert not form.is_valid()
        assert 'username' in form.errors

    def test_form_prevents_duplicate_username(self, faker):
        """
        Test that form prevents creating a user with an existing username
        """
        # Create an existing user
        existing_username = faker.user_name()
        UserFactory(username=existing_username)

        form_data = {
            'username': existing_username,
            'email': faker.email(),
            'first_name': faker.first_name(),
            'last_name': faker.last_name(),
            'password1': 'StrongPassword123!',
            'password2': 'StrongPassword123!'
        }

        form = CustomUserCreationForm(data=form_data)

        assert not form.is_valid()
        assert 'username' in form.errors
