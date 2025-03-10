from django.contrib import admin
from django.db import models
from django.forms import TextInput, Textarea

from events.forms import VideoAssetForm
from events.models import Event, Tag, VideoAsset


class VideoAssetInline(admin.StackedInline):
    """ Custom StackedInline admin for VideoAsset """

    form = VideoAssetForm
    model = VideoAsset
    max_num = 1
    min_num = 1
    can_delete = False
    formfield_overrides = {
        models.CharField: {'widget': TextInput(attrs={'style': 'width: 100%'})},
    }
    # WIP: Automatically detect the file_size and video duration.
    # readonly_fields = ('file_size', 'duration')


class EventAdmin(admin.ModelAdmin):
    """ Custom Admin for Event model """

    list_display = ('title', 'event_type', 'status', 'event_time', 'creator')
    list_filter = ('event_type', 'status', 'event_time')
    search_fields = ('title', 'description')
    filter_horizontal = ('tags', )
    formfield_overrides = {
        models.CharField: {'widget': TextInput(attrs={'style': 'width: 100%'})},
        models.TextField: {'widget': Textarea(attrs={'style': 'width: 100%'})},
    }
    inlines = [VideoAssetInline]
    autocomplete_fields = ('creator', )
    ordering = ('event_time', 'title', 'status')
    list_editable = ('status', )

    fieldsets = (
        (None, {
            'fields': ('creator', 'title', 'description', 'event_time',
                       'event_type', 'status', 'workstream_id', 'is_featured',
                       'tags')
        }),
    )

    def has_delete_permission(self, request, obj=None):
        """ Do not allow deletion of Event directly """
        return False


admin.site.register(Event, EventAdmin)
admin.site.register(Tag)
