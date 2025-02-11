from django import forms
from django.core.exceptions import ValidationError

from events.models import VideoAsset
from events.tasks import download_google_drive_video


class VideoAssetForm(forms.ModelForm):
    """ Custom form for VideoAsset Model """

    google_drive_link = forms.CharField(
        max_length=255,
        required=False,
        label="Google Drive Link (Optional)",
        help_text="Ensure the link is publicly accessible for successful download."
    )

    class Meta:
        model = VideoAsset
        fields = ('title', 'video_file', 'thumbnail')

    def clean(self):
        """ Infer, save and clean the data related to videoasset """
        cleaned_data = super().clean()
        # WIP: Access the google_drive_link from the form's cleaned_data
        # Download the video file, save the file in storage and set the
        # video_file field.
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
            print(google_drive_link, video_asset.id)
            download_google_drive_video.delay(video_asset.id, google_drive_link)
            video_asset.status = VideoAsset.VideoStatus.PROCESSING

        return video_asset
