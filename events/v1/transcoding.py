"""
Turns an uploaded video into the one format every supported browser plays: MP4 with H.264 video and AAC audio.

Uploads may arrive as AVI, WebM or MOV in codecs a browser cannot (or cannot everywhere) decode, such as MPEG-4 part 2,
VP8, ProRes or HEVC. The player always asks for ``video/mp4``, so the stored file has to be an MP4 that really is
playable. Each stream is copied when it already is H.264 (4:2:0) or AAC, which only repackages the file, and
re-encoded otherwise. ``+faststart`` moves the index to the front so seeking works while the file streams.
"""
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import ffmpeg

from django.conf import settings

logger = logging.getLogger("asp_api")

WEB_VIDEO_CODEC = "h264"
WEB_PIXEL_FORMAT = "yuv420p"
WEB_AUDIO_CODEC = "aac"


class TranscodeError(Exception):
    """ The file could not be read or converted, so it would not be playable """


@dataclass(frozen=True)
class ConversionPlan:
    """ Which streams to keep and whether each can be copied as it is """
    video_index: int
    copy_video: bool
    audio_index: Optional[int]
    copy_audio: bool


def _is_cover_art(stream: dict) -> bool:
    return bool(stream.get("disposition", {}).get("attached_pic"))


def plan_conversion(probe: dict) -> ConversionPlan:
    """ Pick the first real video stream and the first audio stream, and decide copy versus re-encode for each """
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and not _is_cover_art(s)), None)
    if video is None:
        raise TranscodeError("The file has no video stream")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return ConversionPlan(
        video_index=video["index"],
        copy_video=video.get("codec_name") == WEB_VIDEO_CODEC and video.get("pix_fmt") == WEB_PIXEL_FORMAT,
        audio_index=audio["index"] if audio else None,
        copy_audio=bool(audio) and audio.get("codec_name") == WEB_AUDIO_CODEC,
    )


def needs_conversion(path: Path) -> bool:
    """ Whether the file is anything other than an MP4 whose streams a browser plays as they are """
    if path.suffix.lower() != ".mp4":
        return True
    try:
        plan = plan_conversion(ffmpeg.probe(str(path)))
    except (ffmpeg.Error, TranscodeError, OSError):
        return True
    return not (plan.copy_video and (plan.audio_index is None or plan.copy_audio))


def probe_duration(path: Path) -> int:
    """ Whole seconds of playing time ffmpeg finds in the file, or 0 when it cannot tell """
    try:
        return int(float(ffmpeg.probe(str(path))["format"]["duration"]))
    except (ffmpeg.Error, OSError, KeyError, ValueError):
        return 0


def build_command(source: Path, output: Path, plan: ConversionPlan) -> list[str]:
    """
    The ffmpeg arguments for ``plan``: only the chosen streams, no subtitles or data tracks.

    Re-encoded video is scaled down to even dimensions, which libx264 requires for 4:2:0.
    """
    command = [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-nostats", "-i", str(source), "-map", f"0:{plan.video_index}"
    ]
    if plan.audio_index is not None:
        command += ["-map", f"0:{plan.audio_index}"]
    if plan.copy_video:
        command += ["-c:v", "copy"]
    else:
        command += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", WEB_PIXEL_FORMAT,
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        ]
    if plan.audio_index is not None:
        command += ["-c:a", "copy"] if plan.copy_audio else ["-c:a", "aac", "-b:a", "160k", "-ac", "2"]
    return command + ["-sn", "-dn", "-movflags", "+faststart", str(output)]


def partial_output_path(destination: Path) -> Path:
    """ Where the conversion writes before renaming into ``destination``, so a killed run leaves only this name """
    return destination.with_name(f"{destination.stem}.partial.mp4")


def _discard_output(output: Path) -> None:
    """ Remove the half-written output; a failure here must not hide the error that led to it """
    try:
        output.unlink(missing_ok=True)
    except OSError:
        logger.exception("video_conversion_cleanup_failed output=%s", output.name)


def make_web_playable(source: Path, destination: Path) -> None:
    """
    Write a browser-playable MP4 of ``source`` to ``destination``. ``source`` is left untouched.

    The output is built next to the destination and renamed into place, so a crash or a timeout never leaves a
    half-written file under the final name. Raises ``TranscodeError`` when the file is unreadable or cannot be
    converted, including when the operating system fails the work (ffmpeg missing, disk full, read-only storage):
    repeating a conversion that takes hours cannot fix those, so they must not escape as a retryable ``OSError``.
    """
    try:
        plan = plan_conversion(ffmpeg.probe(str(source)))
        destination.parent.mkdir(parents=True, exist_ok=True)
    except ffmpeg.Error as exc:
        raise TranscodeError("ffmpeg could not read the file") from exc
    except OSError as exc:
        logger.exception("video_conversion_unavailable source=%s", source.name)
        raise TranscodeError("The conversion could not be started") from exc

    output = partial_output_path(destination)
    try:
        subprocess.run(
            build_command(source, output, plan),
            check=True, capture_output=True, timeout=settings.VIDEO_TRANSCODE_TIMEOUT_SECONDS,
        )
        os.replace(output, destination)
    except subprocess.CalledProcessError as exc:
        logger.error(
            "video_conversion_failed source=%s stderr=%s", source.name, exc.stderr.decode(errors="replace")[-500:]
        )
        raise TranscodeError("ffmpeg could not convert the file") from exc
    except subprocess.TimeoutExpired as exc:
        logger.error("video_conversion_timeout source=%s", source.name)
        raise TranscodeError("The conversion took too long") from exc
    except OSError as exc:
        logger.exception("video_conversion_io_failed source=%s", source.name)
        raise TranscodeError("The converted file could not be written") from exc
    finally:
        _discard_output(output)
    logger.info(
        "video_converted source=%s copied_video=%s copied_audio=%s", source.name, plan.copy_video, plan.copy_audio
    )
