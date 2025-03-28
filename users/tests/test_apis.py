from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

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
