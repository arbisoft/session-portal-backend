import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from celery import shared_task

from django.conf import settings
from django.core.files import File

from events.models import VideoAsset


def _get_file_id(url):
    """Extract file ID from various Google Drive link formats."""
    if 'drive.google.com/file/d/' in url:
        return url.split('/file/d/')[1].split('/')[0]
    if 'drive.google.com/open?id=' in url:
        return urlparse(url).query.split('=')[1]
    return None


def _download_google_drive_file(file_id):
    """Download a file from Google Drive using a session with confirmation handling."""
    session = requests.Session()
    url = "https://drive.google.com/uc"
    params = {'id': file_id, 'export': 'download'}

    response = session.get(url, params=params, stream=True, timeout=30)
    response.raise_for_status()

    token = next((value for key, value in response.cookies.items() if key.startswith('download_warning')), None)
    if token:
        params['confirm'] = token
        response = session.get(url, params=params, stream=True, timeout=30)
        response.raise_for_status()

    if 'text/html' in response.headers.get('content-type', ''):
        response = session.get(
            f"https://drive.usercontent.google.com/download?id={file_id}&confirm=t",
            stream=True,
            timeout=30
        )
        response.raise_for_status()

        if 'text/html' in response.headers.get('content-type', ''):
            raise ValueError("Unable to download file - received HTML instead of video file")

    return response


def _save_video_file(video_asset, response, filename):
    """Save the downloaded video file to VideoAsset."""
    videos_dir = Path(settings.MEDIA_ROOT) / 'videos'
    videos_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as temp_file:
        total_size = sum(temp_file.write(chunk) for chunk in response.iter_content(chunk_size=8192))
        temp_file.flush()

    if total_size < 100:
        raise ValueError(f"Downloaded file is too small: {total_size} bytes")

    with open(temp_file.name, 'rb') as f:
        video_asset.video_file.save(filename, File(f), save=False)

    video_asset.status = VideoAsset.VideoStatus.READY
    video_asset.save()


@shared_task
def download_google_drive_video(video_asset_id, drive_link):
    """Download video from Google Drive and attach it to VideoAsset."""
    try:
        print(f"Starting download for VideoAsset ID: {video_asset_id}")
        video_asset = VideoAsset.objects.get(id=video_asset_id)

        file_id = _get_file_id(drive_link)
        if not file_id:
            raise ValueError(f"Invalid Google Drive link: {drive_link}")

        response = _download_google_drive_file(file_id)

        content_disposition = response.headers.get('content-disposition', '')
        filename = re.search('filename="(.+)"', content_disposition)
        filename = filename.group(1) if filename else f'video_{video_asset_id}.mp4'

        _save_video_file(video_asset, response, filename)

        print(f"Successfully processed VideoAsset ID: {video_asset_id}")
        return True

    except VideoAsset.DoesNotExist:
        print(f"VideoAsset {video_asset_id} does not exist")
    except requests.exceptions.RequestException as e:
        print(f"Error downloading file: {e}")

    VideoAsset.objects.filter(id=video_asset_id).update(status=VideoAsset.VideoStatus.FAILED)
    return False
