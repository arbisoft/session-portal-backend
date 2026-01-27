from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from users.factories import UserFactory

User = get_user_model()


@pytest.mark.django_db
class TestLoginUserAPI:
    """ Test cases for LoginUserView """

    @pytest.fixture
    def api_client(self):
        """ Returns an instance of APIClient """
        return APIClient()

    @pytest.fixture
    def google_user_info(self):
        """ Mock Google user info response """
        return {
            "email": "testuser@arbisoft.com",
            "given_name": "Test",
            "family_name": "User",
            "name": "Test User",
            "id": "123456789",
            "hd": "arbisoft.com"
        }

    @patch("arbisoft_sessions_portal.services.google.google_user_info.GoogleUserInfoService.get_user_info")
    def test_successful_login(self, mock_google_service, api_client, google_user_info):
        """ Test login with a valid Google OAuth2 token """
        mock_google_service.return_value = google_user_info

        response = api_client.post(reverse("login_user"), {"auth_token": "valid_token"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "refresh" in response.data
        assert "access" in response.data
        assert response.data["user_info"]["full_name"] == google_user_info["name"]

        # Ensure user is created in the database
        assert User.objects.filter(email=google_user_info["email"]).exists()

    @patch("arbisoft_sessions_portal.services.google.google_user_info.GoogleUserInfoService.get_user_info")
    def test_login_with_invalid_token(self, mock_google_service, api_client):
        """ Test login failure due to an invalid authentication token """
        mock_google_service.return_value = None

        response = api_client.post(reverse("login_user"), {"auth_token": "invalid_token"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data[0] == "Google Authentication failed"

    @patch("arbisoft_sessions_portal.services.google.google_user_info.GoogleUserInfoService.get_user_info")
    def test_login_with_non_arbisoft_user(self, mock_google_service, api_client, google_user_info):
        """ Test login failure for a non-Arbisoft user when internal user restriction is enabled """
        google_user_info["hd"] = "gmail.com"  # Change domain to non-Arbisoft
        mock_google_service.return_value = google_user_info

        with patch.object(settings, "ALLOW_ONLY_INTERNAL_USERS", True):
            response = api_client.post(reverse("login_user"), {"auth_token": "valid_token"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data[0] == "Not arbisoft user."


@pytest.mark.django_db
class TestLoginWithEmailAPI:
    """ Test cases for LoginWithEmailView """

    @pytest.fixture
    def api_client(self):
        """ Returns an instance of APIClient """
        return APIClient()

    @pytest.fixture
    def user_password(self):
        return "S3cureP@ssw0rd!"

    @pytest.fixture
    def user(self, user_password):
        user = UserFactory()
        user.set_password(user_password)
        user.save(update_fields=["password"])
        return user

    def test_successful_login_with_email_and_password(self, api_client, user, user_password):
        response = api_client.post(
            reverse("login_with_email"),
            {"email": user.email, "password": user_password},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "refresh" in response.data
        assert "access" in response.data
        assert response.data["user_info"]["first_name"] == user.first_name
        assert response.data["user_info"]["last_name"] == user.last_name

    def test_login_with_email_invalid_password(self, api_client, user):
        response = api_client.post(
            reverse("login_with_email"),
            {"email": user.email, "password": "wrong-password"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data[0] == "Invalid email or password"
