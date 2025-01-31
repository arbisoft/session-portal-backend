from django import forms
from django.contrib import admin

from .models import Event, Tag, VideoAsset


class VideoAssetForm(forms.ModelForm):
    """ Custom form for VideoAsset Model """

    google_drive_link = forms.CharField(
        max_length=255, required=False, label="Google Drive Link (Optional)"
    )

    class Meta:
        model = VideoAsset
        fields = ('title', 'video_file', 'duration', 'thumbnail', 'file_size')

    def clean(self):
        """ Infer, save and clean the data related to videoasset """
        cleaned_data = super(VideoAssetForm, self).clean()
        # TODO: Access the google_drive_link from the form's cleaned_data
        # Download the video file, save the file in storage and set the
        # video_file field.
        cleaned_data.pop("google_drive_link")
        return cleaned_data


class VideoAssetInline(admin.StackedInline):
    form = VideoAssetForm
    model = VideoAsset
    max_num = 1
    min_num = 1
    can_delete = False
    # TODO: Automatically detect the file_size and video duration.
    # readonly_fields = ('file_size', 'duration')


class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'event_type', 'status', 'event_time', 'creator')
    list_filter = ('event_type', 'status', 'event_time')
    search_fields = ('title', 'description')
    inlines = [VideoAssetInline]

    fieldsets = (
        (None, {
            'fields': ('creator', 'title', 'description', 'event_time',
                       'event_type', 'status', 'workstream_id', 'is_featured',
                       'tags')
        }),
    )

    def has_delete_permission(self, request, obj=None):
        """ Do not allow delete of Event directly """
        return False


admin.site.register(Event, EventAdmin)
admin.site.register(Tag)
