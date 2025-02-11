import logging
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests


from celery import shared_task


from django.core.files import File
from django.conf import settings

from events.models import VideoAsset

logger = logging.getLogger(__name__)


@shared_task
def download_google_drive_video(video_asset_id, drive_link):
    """
    Download video from Google Drive and attach it to VideoAsset

    Args:
        video_asset_id (int): ID of the VideoAsset
        drive_link (str): Google Drive sharing link

    Returns:
        bool: True if successful, False otherwise
    """

    def get_file_id(url):
        # Handle different Google Drive URL formats
        if 'drive.google.com/file/d/' in url:
            return url.split('/file/d/')[1].split('/')[0]
        if 'drive.google.com/open?id=' in url:
            return urlparse(url).query.split('=')[1]
        return None

    def get_confirm_token(response):
        for key, value in response.cookies.items():
            if key.startswith('download_warning'):
                return value
        return None

    video_asset = VideoAsset.objects.get(id=video_asset_id)
    try:
        logger.info(f"Starting download for VideoAsset ID: {video_asset_id}")

        file_id = get_file_id(drive_link)
        if not file_id:
            raise ValueError(f"Invalid Google Drive link format: {drive_link}")

        session = requests.Session()
        url = "https://drive.google.com/uc"
        params = {
            'id': file_id,
            'export': 'download'
        }

        logger.debug(f"Initiating first request to get confirmation token for file ID: {file_id}")
        response = session.get(url, params=params, stream=True, timeout=30)
        response.raise_for_status()

        token = get_confirm_token(response)
        if token:
            params['confirm'] = token
            logger.debug("Confirmation token received, initiating second request")
            response = session.get(url, params=params, stream=True, timeout=30)
            response.raise_for_status()

        content_type = response.headers.get('content-type', '')
        if 'text/html' in content_type:
            logger.debug("Received HTML response, trying direct download URL")
            direct_url = f"https://drive.usercontent.google.com/download?id={file_id}&confirm=t"
            response = session.get(direct_url, stream=True, timeout=30)
            response.raise_for_status()

            if 'text/html' in response.headers.get('content-type', ''):
                raise ValueError("Unable to download file - received HTML instead of video file")

        content_disposition = response.headers.get('content-disposition', '')
        filename_match = re.search('filename="(.+)"', content_disposition)
        filename = filename_match.group(1) if filename_match else f'video_{video_asset_id}.mp4'

        logger.info(f"Downloading file: {filename}")

        videos_dir = Path(settings.MEDIA_ROOT) / 'videos'
        videos_dir.mkdir(parents=True, exist_ok=True)

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
        total_size = 0

        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                temp_file.write(chunk)
                total_size += len(chunk)

        temp_file.flush()
        logger.debug(f"Downloaded file size: {total_size} bytes")

        if total_size < 100:
            raise ValueError(f"Downloaded file is too small to be a video: {total_size} bytes")

        with open(temp_file.name, 'rb') as f:
            video_asset.video_file.save(
                filename,
                File(f),
                save=False
            )

        video_asset.status = VideoAsset.VideoStatus.PROCESSING
        video_asset.save()

        logger.info(f"Successfully processed VideoAsset ID: {video_asset_id}")
        return True

    except VideoAsset.DoesNotExist:
        logger.info(f"VideoAsset with id {video_asset_id} does not exist")
        video_asset.status = VideoAsset.VideoStatus.FAILED
        video_asset.save()
        return False
    except requests.exceptions.RequestException as e:
        logger.info(f"Error downloading file: {str(e)}")
        video_asset.status = VideoAsset.VideoStatus.FAILED
        video_asset.save()
        return False

    logger.info(f"Unexpected error: {str(e)}")
    video_asset.status = VideoAsset.VideoStatus.FAILED
    video_asset.save()
    return False
