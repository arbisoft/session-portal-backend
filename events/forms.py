from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import TextInput

from events.models import Event, EventPresenter, VideoAsset

User = get_user_model()


class VideoAssetForm(forms.ModelForm):
    """ Custom form for VideoAsset Model """

    google_drive_link = forms.CharField(
        max_length=255,
        required=False,
        label="Google Drive Link (Optional)",
        help_text="Ensure the link is publicly accessible for successful download.",
        widget=TextInput(attrs={"style": "width: 100%"}),
    )

    class Meta:
        model = VideoAsset
        fields = ('title', 'video_file', 'thumbnail',)

    def clean(self):
        """ Infer, save and clean the data related to videoasset """
        cleaned_data = super().clean()
        google_drive_link = cleaned_data.get('google_drive_link')
        video_file = cleaned_data.get('video_file')

        if not video_file and not google_drive_link:
            raise ValidationError("You must provide either a video file or a Google Drive link.")

        if video_file and google_drive_link:
            raise ValidationError("Please provide only one: either a video file or a Google Drive link.")

        return cleaned_data


class EventAdminForm(forms.ModelForm):
    """ Custom form for Event Model """
    videoasset = forms.ModelChoiceField(
        queryset=VideoAsset.objects.none(),
        required=False,
        label="Video Asset",
        help_text="Select a video to associate with this event."
    )

    class Meta:
        model = Event
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_event = self.instance

        # Disable slug field if the instance is new
        if current_event and current_event.pk:
            self.fields['slug'].disabled = False
        else:
            self.fields['slug'].disabled = True

        # Populate videoasset queryset based on the current event
        # If the event is new, show all video assets without an event
        qs = VideoAsset.objects.filter(event__isnull=True)

        if current_event.pk:
            qs = qs | VideoAsset.objects.filter(event=current_event)

        self.fields["videoasset"].queryset = qs.distinct()

        # This ensures the current value is selected
        self.initial["videoasset"] = (
            VideoAsset.objects.filter(event=current_event).first()
            if current_event.pk else None
        )


class EventPresenterForm(forms.ModelForm):
    """ Custom form for EventPresenter Model """

    class Meta:
        model = EventPresenter
        fields = "__all__"
