from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from django.contrib.auth import get_user_model
from django.db.models import TextChoices

User = get_user_model()


class LoginUserSerializer(serializers.Serializer):
    """ Serializer for the login user """

    auth_token = serializers.CharField(required=True)


class EmailLoginSerializer(serializers.Serializer):
    """ Serializer for email/password login """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class UserSearchSerializer(serializers.ModelSerializer):
    """ Serializer for user search results """
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'full_name', 'email')

    @staticmethod
    def get_full_name(obj) -> str:
        """ Full name of the user, falling back to the email because Google-created usernames are synthesized """
        return obj.get_full_name() or obj.email


class UserRole(TextChoices):
    """ Role of a user, derived from Django's `is_superuser` and `is_staff` flags """
    ADMIN = 'admin', 'Admin'
    STAFF = 'staff', 'Staff'
    USER = 'user', 'User'


class CurrentUserSerializer(UserSearchSerializer):
    """ Serializer for the authenticated user's basic information """
    role = serializers.SerializerMethodField()

    class Meta(UserSearchSerializer.Meta):
        fields = UserSearchSerializer.Meta.fields + ('is_staff', 'role')
        read_only_fields = fields

    @staticmethod
    @extend_schema_field(serializers.ChoiceField(choices=UserRole.choices))
    def get_role(obj) -> str:
        """ Superusers are admins even without `is_staff`; staff-only endpoints still gate on `is_staff` """
        if obj.is_superuser:
            return UserRole.ADMIN
        if obj.is_staff:
            return UserRole.STAFF
        return UserRole.USER
