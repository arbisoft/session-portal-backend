from rest_framework import serializers

class EventTypeSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()

    def to_representation(self, instance):
        return {
            'label': instance[0],
            'key': instance[1]
        }
