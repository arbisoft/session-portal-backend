from rest_framework import serializers


class LoginUserSerializer(serializers.Serializer):
    """ Serializer for the login user """

    auth_token = serializers.CharField(required=True)


class EmailLoginSerializer(serializers.Serializer):
    """ Serializer for email/password login """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)
