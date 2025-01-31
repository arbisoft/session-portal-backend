from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from django.conf import settings
from django.contrib.auth import get_user_model

from arbisoft_sessions_portal.services.google.google_user_info import GoogleUserInfoService
from users.v1.serializers import LoginUserSerializer

user_model = get_user_model()


class LoginUserView(APIView):
    """ View for logging in the user """

    permission_classes = []

    def post(self, request):
        """ Log in the user """

        login_data = LoginUserSerializer(data=request.data)
        login_data.is_valid(raise_exception=True)

        google_service = GoogleUserInfoService(login_data.data.get("auth_token"))
        user_info = google_service.get_user_info()

        if not user_info:
            raise ValidationError("Google Authentication failed")

        if user_info.get("hd") != "arbisoft.com" and settings.ALLOW_ONLY_INTERNAL_USERS:
            raise ValidationError("Not arbisoft user.")

        user = user_model.objects.filter(email=user_info['email']).first()
        if not user:
            user = user_model.objects.create_user(
                username=f"{user_info['email']}_{user_info['id']}",
                email=user_info['email'],
                first_name=user_info['given_name'],
                last_name=user_info['family_name']
            )

        refresh = RefreshToken.for_user(user)

        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user_info': {
                'full_name': user_info.get('name'),
                'first_name': user_info.get('given_name'),
                'last_name': user_info.get('family_name'),
                'avatar': user_info.get('picture')
            }
        })


class HelloWorldView(APIView):
    """ View for testing the API """

    @extend_schema(
        responses={200: {"type": "string", "example": "Hello World"}}
    )
    def get(self, request):
        """
        This endpoint returns a simple "Hello World" response.
        It can be used to verify that the API is up and running.
        """
        return Response("Hello World")
