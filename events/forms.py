from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import TextInput

from events.models import EventPresenter, VideoAsset
from events.tasks import download_google_drive_video

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
        fields = ('title', 'video_file', 'thumbnail')

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

    def save(self, commit=True):
        google_drive_link = self.cleaned_data.get('google_drive_link')
        video_asset = super().save()

        if google_drive_link:
            download_google_drive_video.delay(video_asset.id, google_drive_link)
            video_asset.status = VideoAsset.VideoStatus.PROCESSING
            video_asset.save()

        return video_asset


class EventPresenterForm(forms.ModelForm):
    """ Custom form to show first_name and last_name in the dropdown """
    user = forms.ModelChoiceField(
        queryset=User.objects.all().order_by("first_name", "last_name"),
        label="Presenter"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].label_from_instance = lambda obj: f"{obj.first_name} {obj.last_name}"

    class Meta:
        model = EventPresenter
        fields = "__all__"
