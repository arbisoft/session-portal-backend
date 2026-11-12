"""
Authenticated, Range-aware streaming of stored video files.

Videos are never served from ``MEDIA_URL``: every byte goes through a view that has already checked the caller's
credentials, so a copied link is useless without a valid session/token. Responses carry ``Cache-Control:
private, no-store`` so the bytes stay out of shared caches and CDNs.
"""
import logging
import mimetypes
import os
import re
from typing import BinaryIO, Iterator

from rest_framework.negotiation import BaseContentNegotiation

from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils.http import http_date, parse_http_date_safe

from events.v1.uploads import file_extension

logger = logging.getLogger("asp_api")

CHUNK_SIZE = 1024 * 1024
DEFAULT_PLAYBACK_TYPE = 'video/mp4'
# The type a player should declare, which is not always the file's own MIME type: browsers that cannot name
# ``video/quicktime`` still play an H.264 MOV when it is declared as the MP4 family it belongs to. The stream response
# (``_build_response``) deliberately keeps the file's own ``video/quicktime`` header, so the two differ for ``.mov``.
PLAYBACK_TYPES = {
    'mp4': 'video/mp4',
    'mov': 'video/mp4',
    'webm': 'video/webm',
}
RANGE_RE = re.compile(r'^bytes=(\d*)-(\d*)$')


class IgnoreClientContentNegotiation(BaseContentNegotiation):
    """ The body is a file, not a negotiated representation: a strict ``Accept`` header must not cause a 406 """

    def select_parser(self, request, parsers):
        """ Use the first configured parser """
        return parsers[0]

    def select_renderer(self, request, renderers, format_suffix=None):
        """ Use the first configured renderer (only error responses are rendered) """
        renderer = renderers[0]
        return renderer, renderer.media_type


def video_playback_type(name: str) -> str:
    """ Media type a player should declare for the stored video file called ``name`` """
    return PLAYBACK_TYPES.get(file_extension(name)) or mimetypes.guess_type(name)[0] or DEFAULT_PLAYBACK_TYPE


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """
    Resolve a single ``bytes=`` range into an inclusive ``(start, end)`` pair.

    Returns ``None`` when the header should be ignored (absent, malformed, multi-range, or a range-spec whose last
    position precedes its first, which RFC 9110 treats as invalid) and raises ``ValueError`` when the range is valid
    but unsatisfiable: a first position at or past the end, a zero-length suffix, or any range on an empty file.
    A suffix range (``bytes=-N``) selects the last N bytes.
    """
    match = RANGE_RE.match(header.strip()) if header else None
    if not match:
        return None
    first, last = match.groups()
    if not first and not last:
        return None
    if first and last and int(last) < int(first):
        return None
    if size == 0:
        raise ValueError('unsatisfiable')
    if not first:
        length = int(last)
        if length == 0:
            raise ValueError('unsatisfiable')
        return max(size - length, 0), size - 1
    start = int(first)
    if start >= size:
        raise ValueError('unsatisfiable')
    end = min(int(last), size - 1) if last else size - 1
    return start, end


class FileRangeIterator:
    """ Iterate over ``length`` bytes of an already opened file from ``start``; ``close()`` releases the handle """

    def __init__(self, file_obj: BinaryIO, start: int, length: int):
        self.file_obj = file_obj
        self.start = start
        self.length = length

    def __iter__(self) -> Iterator[bytes]:
        self.file_obj.seek(self.start)
        remaining = self.length
        while remaining > 0:
            chunk = self.file_obj.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                logger.warning('Video file ended %d bytes before the advertised Content-Length', remaining)
                break
            remaining -= len(chunk)
            yield chunk

    def close(self) -> None:
        """ Called by the response when it is closed, whether or not the body was read """
        self.file_obj.close()


def _if_range_matches(request, etag: str, mtime: int) -> bool:
    """ ``If-Range`` guards a partial response: a stale validator means the whole file must be sent """
    value = request.headers.get('If-Range')
    if not value:
        return True
    if value.startswith(('"', 'W/')):
        return value == etag
    parsed = parse_http_date_safe(value)
    return parsed is not None and parsed == mtime


def _build_response(request, file_obj: BinaryIO, name: str) -> HttpResponse:
    """ Build the response from the opened handle's own ``fstat`` so size, validators and body describe one file """
    stat = os.fstat(file_obj.fileno())
    size, mtime = stat.st_size, int(stat.st_mtime)
    etag = f'"{stat.st_mtime_ns:x}-{size:x}"'

    try:
        byte_range = _parse_range(request.headers.get('Range', ''), size)
    except ValueError:
        file_obj.close()
        response = HttpResponse(status=416)
        response['Content-Range'] = f'bytes */{size}'
        return response

    if byte_range and not _if_range_matches(request, etag, mtime):
        byte_range = None

    start, end = byte_range or (0, size - 1)
    length = end - start + 1

    response = StreamingHttpResponse(
        FileRangeIterator(file_obj, start, length),
        status=206 if byte_range else 200,
        content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream',
    )
    response['Content-Length'] = str(length)
    response['Accept-Ranges'] = 'bytes'
    response['ETag'] = etag
    response['Last-Modified'] = http_date(mtime)
    response['Content-Disposition'] = 'inline'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    if byte_range:
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
    return response


def stream_file_field(request, file_field) -> HttpResponse:
    """
    Build a 200/206/416 response for ``file_field`` honouring the request's ``Range`` header.

    The file is opened once, before the status line is committed, and size, mtime and ETag are read from that handle,
    so a file replaced mid-request cannot make the headers describe a different file than the body. The handle is
    closed by the response, or here on the 416 branch and on any error. Raises ``Http404`` when the file is missing.
    """
    try:
        file_obj = file_field.storage.open(file_field.name, 'rb')
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise Http404 from exc

    try:
        return _build_response(request, file_obj, file_field.name)
    except BaseException:
        file_obj.close()
        raise
