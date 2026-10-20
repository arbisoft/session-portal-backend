from rest_framework import serializers

from django.contrib.auth import get_user_model

User = get_user_model()


class LoginUserSerializer(serializers.Serializer):
    """ Serializer for the login user """

    auth_token = serializers.CharField(required=True)


class EmailLoginSerializer(serializers.Serializer):
    """ Serializer for email/password login """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)


def get_user_full_name(user) -> str:
    """ Full name of the user, falling back to the email because Google-created usernames are synthesized """
    return user.get_full_name() or user.email


class UserSearchSerializer(serializers.ModelSerializer):
    """ Serializer for user search results """
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'full_name', 'email')

    @staticmethod
    def get_full_name(obj) -> str:
        """ Get the full name of a user """
        return get_user_full_name(obj)


class CurrentUserSerializer(serializers.ModelSerializer):
    """ Serializer for the authenticated user's basic information """

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "first_name", "last_name", "full_name", "email", "is_staff")
        read_only_fields = fields

    @staticmethod
    def get_full_name(obj) -> str:
        """ Get the full name of a user """
        return get_user_full_name(obj)
