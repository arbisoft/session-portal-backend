from django.contrib import admin
from django.db import models
from django.forms import Textarea, TextInput

from events.forms import EventPresenterForm, VideoAssetForm
from events.models import Event, EventPresenter, Tag, VideoAsset


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


class EventPresenterInline(admin.StackedInline):
    """ Custom StackedInline admin for EventPresenter """
    model = EventPresenter
    form = EventPresenterForm
    extra = 1


class EventAdmin(admin.ModelAdmin):
    """ Custom Admin for Event model """

    list_display = ('title', 'event_type', 'status', 'event_time', 'creator', 'get_presenters')
    list_filter = ('event_type', 'status', 'event_time')
    search_fields = ('title', 'description')
    filter_horizontal = ('tags', )
    formfield_overrides = {
        models.CharField: {'widget': TextInput(attrs={'style': 'width: 100%'})},
        models.TextField: {'widget': Textarea(attrs={'style': 'width: 100%'})},
    }
    inlines = [EventPresenterInline, VideoAssetInline]
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

    def get_presenters(self, obj):
        """ Fetch Presenter First Name and Last Name """
        return ", ".join([f"{p.user.first_name} {p.user.last_name}" for p in obj.presenters.all()])

    get_presenters.short_description = "Presenters"


admin.site.register(Event, EventAdmin)
admin.site.register(Tag)
