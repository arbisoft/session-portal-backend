from django import forms
from events.models import VideoAsset


class VideoAssetForm(forms.ModelForm):
    """ Custom form for VideoAsset Model """

    google_drive_link = forms.CharField(
        max_length=255, required=False, label="Google Drive Link (Optional)"
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
        cleaned_data.pop("google_drive_link")
        return cleaned_data
