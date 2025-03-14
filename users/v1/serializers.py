from rest_framework import serializers

from django.contrib.auth import get_user_model

User = get_user_model()


class LoginUserSerializer(serializers.Serializer):
    """ Serializer for the login user """

    auth_token = serializers.CharField(required=True)


class UserSerializer(serializers.ModelSerializer):
    """ Serializer to fetch user details (first name, last name, email) """
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "email"]
