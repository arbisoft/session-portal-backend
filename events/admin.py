from django.contrib import admin

from .models import Event, Tag, VideoAsset

admin.site.register(Event)
admin.site.register(VideoAsset)
admin.site.register(Tag)
