from rest_framework import serializers
class LoginUserSerializer(serializers.Serializer):

    auth_token = serializers.CharField(required=True)
