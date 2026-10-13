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


class UserSearchSerializer(serializers.ModelSerializer):
    """ Serializer for user search results """
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'full_name', 'email')

    @staticmethod
    def get_full_name(obj):
        """ Get the full name of a user """
        return f"{obj.first_name} {obj.last_name}".strip()
