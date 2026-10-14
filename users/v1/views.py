from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q

from arbisoft_sessions_portal.services.google.google_user_info import GoogleUserInfoService
from users.permissions import IsStaffPermission
from users.v1.serializers import EmailLoginSerializer, LoginUserSerializer, UserSearchSerializer

user_model = get_user_model()


class LoginUserView(APIView):
    """ View for logging in the user """

    permission_classes = []

    @extend_schema(
        request=LoginUserSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "refresh": {
                        "type": "string",
                        "description": "JWT refresh token",
                        "example": "eyJ0eXAiOiJKV1QiLCJhbGc..."
                    },
                    "access": {
                        "type": "string",
                        "description": "JWT access token",
                        "example": "eyJ0eXAiOiJKV1QiLCJhbGc..."
                    },
                    "user_info": {
                        "type": "object",
                        "properties": {
                            "full_name": {
                                "type": "string",
                                "example": "John Doe"
                            },
                            "first_name": {
                                "type": "string",
                                "example": "John"
                            },
                            "last_name": {
                                "type": "string",
                                "example": "Doe"
                            },
                            "avatar": {
                                "type": "string",
                                "format": "uri",
                                "example": "https://lh3.googleusercontent.com/a/photo"
                            },
                            "is_staff": {
                                "type": "boolean",
                                "description": "Whether the user can upload videos and create events",
                                "example": False
                            }
                        }
                    }
                }
            },
            400: {
                "type": "object",
                "properties": {
                    "detail": {
                        "type": "string",
                        "enum": [
                            "Google Authentication failed",
                            "Not arbisoft user."
                        ]
                    }
                }
            }
        },
        description="Authenticate user using Google OAuth2 token and return JWT tokens",
    )
    def post(self, request):
        """ Log in the user """

        login_data = LoginUserSerializer(data=request.data)
        login_data.is_valid(raise_exception=True)

        google_service = GoogleUserInfoService(login_data.data.get("auth_token"))
        user_info = google_service.get_user_info()

        if not user_info:
            raise ValidationError("Google Authentication failed")

        if user_info.get("hd") not in ["arbisoft.com", "edly.io"] and settings.ALLOW_ONLY_INTERNAL_USERS:
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
                'avatar': user_info.get('picture'),
                'is_staff': user.is_staff,
            }
        })


class LoginWithEmailView(APIView):
    """ View for logging in the user with email """

    permission_classes = []

    @extend_schema(
        request=EmailLoginSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "refresh": {
                        "type": "string",
                        "description": "JWT refresh token",
                        "example": "eyJ0eXAiOiJKV1QiLCJhbGc..."
                    },
                    "access": {
                        "type": "string",
                        "description": "JWT access token",
                        "example": "eyJ0eXAiOiJKV1QiLCJhbGc..."
                    },
                    "user_info": {
                        "type": "object",
                        "properties": {
                            "full_name": {
                                "type": "string",
                                "example": "John Doe"
                            },
                            "first_name": {
                                "type": "string",
                                "example": "John"
                            },
                            "last_name": {
                                "type": "string",
                                "example": "Doe"
                            },
                            "avatar": {
                                "type": ["string", "null"],
                                "format": "uri",
                                "example": None,
                                "description": "User avatar URL, can be null"
                            },
                            "is_staff": {
                                "type": "boolean",
                                "description": "Whether the user can upload videos and create events",
                                "example": False
                            }
                        }
                    }
                }
            },
            400: {
                "type": "object",
                "properties": {
                    "detail": {
                        "type": "string",
                        "enum": [
                            "Email and password are required",
                            "Invalid email or password"
                        ]
                    }
                }
            }
        },
        description="Authenticate user using email and password and return JWT tokens",
    )
    def post(self, request):
        """ Log in the user with email """
        serializer = EmailLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        # Django's default authentication backend uses the `username` field, not `email`.
        # We first fetch the user by email, then authenticate using their username.
        user = user_model.objects.filter(email=email).first()
        if user:
            user = authenticate(username=user.username, password=password)

        if not user:
            raise ValidationError("Invalid email or password")

        refresh = RefreshToken.for_user(user)
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user_info': {
                'full_name': user.get_full_name(),
                'first_name': user.first_name,
                'last_name': user.last_name,
                'avatar': None,
                'is_staff': user.is_staff,
            }
        })


class UserSearchView(ListAPIView):
    """ View for searching users by name or email (staff only) """

    permission_classes = [IsAuthenticated, IsStaffPermission]
    serializer_class = UserSearchSerializer
    pagination_class = None

    def get_queryset(self):
        q = self.request.query_params.get('q', '').strip()
        if not q:
            return user_model.objects.none()
        return user_model.objects.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q)
        ).order_by('first_name')[:20]
