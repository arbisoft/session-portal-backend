from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

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
        """ Returns a user password """
        return "S3cureP@ssw0rd!"

    @pytest.fixture
    def user(self, user_password):
        """ Returns a user """
        user = UserFactory()
        user.set_password(user_password)
        user.save(update_fields=["password"])
        return user

    def test_successful_login_with_email_and_password(self, api_client, user, user_password):
        """ Test successful login with email and password """
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
        """ Test login with email and invalid password """
        response = api_client.post(
            reverse("login_with_email"),
            {"email": user.email, "password": "wrong-password"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data[0] == "Invalid email or password"


@pytest.mark.django_db
class TestCurrentUserAPI:
    """ Test cases for CurrentUserView """

    @pytest.fixture
    def api_client(self):
        """ Returns an instance of APIClient """
        return APIClient()

    @pytest.fixture
    def user(self):
        """ Returns a user """
        return UserFactory(first_name="Test", last_name="User")

    @staticmethod
    def _authenticate(api_client, user):
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def test_returns_authenticated_user(self, api_client, user):
        """ Test that a valid Bearer token returns the user's basic information """
        self._authenticate(api_client, user)

        response = api_client.get(reverse("current_user"))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            "id": user.id,
            "first_name": "Test",
            "last_name": "User",
            "full_name": "Test User",
            "email": user.email,
            "is_staff": False,
        }

    def test_full_name_falls_back_to_email(self, api_client):
        """ Test that a user without a name gets the email as full name """
        user = UserFactory(first_name="", last_name="")
        self._authenticate(api_client, user)

        response = api_client.get(reverse("current_user"))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["full_name"] == user.email

    @pytest.mark.parametrize("is_staff, is_superuser", [
        (False, False),
        (True, False),
        (False, True),
    ])
    def test_is_staff_mirrors_flag_no_role(self, api_client, is_staff, is_superuser):
        """ Test that is_staff equals the stored flag and no role is returned """
        user = UserFactory(is_staff=is_staff, is_superuser=is_superuser)
        self._authenticate(api_client, user)

        response = api_client.get(reverse("current_user"))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_staff"] is is_staff
        assert "role" not in response.data

    def test_does_not_expose_sensitive_fields(self, api_client, user):
        """ Test that the password is never part of the response """
        self._authenticate(api_client, user)

        response = api_client.get(reverse("current_user"))

        assert "password" not in response.data

    def test_missing_token(self, api_client):
        """ Test that a request without credentials is rejected with 401 """
        response = api_client.get(reverse("current_user"))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response["WWW-Authenticate"].startswith("Bearer")

    def test_invalid_token(self, api_client):
        """ Test that a malformed token is rejected with 401 """
        api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-valid-token")

        response = api_client.get(reverse("current_user"))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_token_is_rejected(self, api_client, user):
        """ Test that a refresh token cannot be used as an access token """
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user)}")

        response = api_client.get(reverse("current_user"))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_inactive_user_is_rejected(self, api_client, user):
        """ Test that a token of a deactivated user is rejected with 401 """
        self._authenticate(api_client, user)
        user.is_active = False
        user.save(update_fields=["is_active"])

        response = api_client.get(reverse("current_user"))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_session_authentication_is_not_accepted(self, api_client, user):
        """ Test that only the Bearer token authenticates this endpoint """
        api_client.force_login(user)

        response = api_client.get(reverse("current_user"))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_write_methods_not_allowed(self, api_client, user):
        """ Test that the endpoint is read only """
        self._authenticate(api_client, user)

        response = api_client.post(reverse("current_user"), {"first_name": "Hacker"}, format="json")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
class TestUserSearchAPI:
    """ Test cases for UserSearchView """

    @pytest.fixture
    def api_client(self):
        """ Returns an instance of APIClient """
        return APIClient()

    @pytest.fixture
    def staff_user(self):
        """ Returns a staff user """
        return UserFactory(is_staff=True, first_name="Staff", last_name="Member", email="staff@arbisoft.com")

    def test_nameless_user_full_name_is_email(self, api_client, staff_user):
        """ Test that a user without a name is returned with the email as full name """
        nameless = UserFactory(first_name="", last_name="", email="nameless.person@arbisoft.com")
        api_client.force_authenticate(staff_user)

        response = api_client.get(reverse("user-search"), {"q": "nameless.person"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0] == {
            "id": nameless.id,
            "first_name": "",
            "last_name": "",
            "full_name": "nameless.person@arbisoft.com",
            "email": "nameless.person@arbisoft.com",
        }

    def test_named_user_full_name_is_joined_name(self, api_client, staff_user):
        """ Test that a user with a name keeps first and last name as full name """
        named = UserFactory(first_name="Ada", last_name="Lovelace", email="ada@arbisoft.com")
        api_client.force_authenticate(staff_user)

        response = api_client.get(reverse("user-search"), {"q": "ada"})

        assert response.status_code == status.HTTP_200_OK
        assert [item["id"] for item in response.data] == [named.id]
        assert response.data[0]["full_name"] == "Ada Lovelace"

    def test_anonymous_is_rejected(self, api_client):
        """ Test that an anonymous request is rejected with 401 """
        response = api_client.get(reverse("user-search"), {"q": "ada"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_staff_is_forbidden(self, api_client):
        """ Test that a non-staff user is rejected with 403 """
        api_client.force_authenticate(UserFactory(is_staff=False))

        response = api_client.get(reverse("user-search"), {"q": "ada"})

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_blank_query_returns_empty_list(self, api_client, staff_user):
        """ Test that a blank query returns no users """
        api_client.force_authenticate(staff_user)

        response = api_client.get(reverse("user-search"), {"q": "  "})

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
