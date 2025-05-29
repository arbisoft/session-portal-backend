from django.contrib import admin
from django.db import models
from django.forms import Textarea, TextInput

from events.forms import EventAdminForm, EventPresenterForm, VideoAssetForm
from events.models import Event, EventPresenter, Playlist, Tag, VideoAsset
from events.tasks import download_google_drive_video


class VideoAssetAdmin(admin.ModelAdmin):
    """ Custom Admin for VideoAsset model """
    form = VideoAssetForm
    list_display = ('title', 'event', 'status', 'duration', 'file_size', 'created')
    search_fields = ('title',)
    autocomplete_fields = ('event',)
    formfield_overrides = {
        models.CharField: {'widget': TextInput(attrs={'style': 'width: 100%'})},
    }

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        google_drive_link = form.cleaned_data.get("google_drive_link")
        if google_drive_link:
            download_google_drive_video.delay(obj.id, google_drive_link)
            obj.status = VideoAsset.VideoStatus.PROCESSING
            obj.save(update_fields=["status"])


class EventPresenterInline(admin.StackedInline):
    """ Custom StackedInline admin for EventPresenter """
    model = EventPresenter
    form = EventPresenterForm
    extra = 1
    autocomplete_fields = ('user',)


class EventAdmin(admin.ModelAdmin):
    """ Custom Admin for Event model """
    form = EventAdminForm
    list_display = ('title', 'event_type', 'status', 'event_time', 'creator', 'get_presenters')
    search_fields = ('title', 'description')
    filter_horizontal = ('tags', 'playlists')
    formfield_overrides = {
        models.CharField: {'widget': TextInput(attrs={'style': 'width: 100%'})},
        models.TextField: {'widget': Textarea(attrs={'style': 'width: 100%'})},
    }
    inlines = [EventPresenterInline]
    autocomplete_fields = ('creator', )
    ordering = ('event_time', 'title', 'status')
    list_editable = ('status', )

    fieldsets = (
        (None, {
            'fields': ('creator', 'title', 'description', 'event_time',
                       'event_type', 'status', 'is_featured',
                       'tags', 'playlists', 'videoasset')
        }),
    )

    def has_delete_permission(self, request, obj=None):
        """ Do not allow deletion of Event directly """
        return False

    def get_presenters(self, obj):
        """ Fetch Presenter First Name and Last Name """
        return ", ".join([f"{p.first_name} {p.last_name}" for p in obj.presenters.all()])

    get_presenters.short_description = "Presenters"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # Handle assignment here after Event has a valid PK
        videoasset = form.cleaned_data.get("videoasset")
        if videoasset:
            # Unlink any previous link first
            VideoAsset.objects.filter(event=obj).exclude(id=videoasset.id).update(event=None)

            videoasset.event = obj
            videoasset.save(update_fields=["event"])


admin.site.register(Event, EventAdmin)
admin.site.register(Playlist)
admin.site.register(Tag)
admin.site.register(VideoAsset, VideoAssetAdmin)
