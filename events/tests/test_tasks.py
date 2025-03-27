import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests
import responses

from events.factories import VideoAssetFactory
from events.models import VideoAsset
from events.tasks import _download_google_drive_file, _get_file_id, _save_video_file, download_google_drive_video


@pytest.mark.django_db
class TestGoogleDriveDownloadTasks:
    """ Test cases for Google Drive download tasks """
    def test_get_file_id_standard_link(self):
        """ Test extracting file ID from standard Google Drive link """
        url = "https://drive.google.com/file/d/1ABC123xyz/view"
        file_id = _get_file_id(url)
        assert file_id == "1ABC123xyz"

    def test_get_file_id_open_link(self):
        """ Test extracting file ID from Google Drive open link """
        url = "https://drive.google.com/open?id=1ABC123xyz"
        file_id = _get_file_id(url)
        assert file_id == "1ABC123xyz"

    def test_get_file_id_invalid_link(self):
        """ Test handling of invalid Google Drive link """
        url = "https://example.com/invalid"
        file_id = _get_file_id(url)
        assert file_id is None

    @responses.activate
    def test_download_google_drive_file_with_warning(self):
        """ Test downloading a file from Google Drive with download warning """
        file_id = "test_file_id"

        # First response with download warning
        responses.add(
            responses.GET,
            f"https://drive.google.com/uc?id={file_id}&export=download",
            body="Warning page",
            headers={'content-type': 'text/html', 'Set-Cookie': 'download_warning=token123'},
            status=200
        )

        # Successful download response
        responses.add(
            responses.GET,
            f"https://drive.google.com/uc?id={file_id}&export=download&confirm=token123",
            body=b"File content",
            headers={'content-type': 'video/mp4'},
            status=200
        )

        response = _download_google_drive_file(file_id)
        assert response.content == b"File content"

    @patch('events.tasks._get_file_id')
    def test_download_google_drive_video_invalid_link(self, mock_get_file_id):
        """ Test handling of invalid Google Drive link """
        video_asset = VideoAssetFactory(status=VideoAsset.VideoStatus.PROCESSING)

        mock_get_file_id.return_value = None

        with pytest.raises(ValueError, match="Invalid Google Drive link: https://invalid.link"):
            download_google_drive_video(video_asset.id, "https://invalid.link")

    @patch('events.tasks._get_file_id')
    @patch('events.tasks._download_google_drive_file')
    def test_download_google_drive_video_download_error(
        self,
        mock_download_file,
        mock_get_file_id
    ):
        """ Test handling of download errors """
        video_asset = VideoAssetFactory(status=VideoAsset.VideoStatus.PROCESSING)

        mock_get_file_id.return_value = "test_file_id"
        mock_download_file.side_effect = requests.exceptions.RequestException("Download error")

        result = download_google_drive_video(video_asset.id, "https://drive.google.com/file/d/test")
        video_asset.refresh_from_db()

        assert result is False
        assert video_asset.status == VideoAsset.VideoStatus.FAILED
