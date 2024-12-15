from rest_framework import serializers

class EventTypeSerializer(serializers.Serializer):
    label = serializers.CharField()
    key = serializers.CharField()
