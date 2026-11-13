"""
Resumable upload helpers.

Protocol: the client creates an ``UploadSession`` and then PATCHes consecutive chunks to it. Each chunk is appended to
a partial file at exactly ``session.offset`` and the new offset is committed with the same row lock that guarded the
write, so the committed offset only ever names bytes that were fsynced. A crash between the write and the commit
leaves surplus bytes behind the committed offset, which the next writer truncates away.

When the last byte is committed the session moves to ``FINALIZING`` and a Celery task verifies the file, converts it
into the video storage and creates the ``VideoAsset``. Every step of that task is safe to run again. The conversion
can take hours, so it runs without a transaction; only registering its outcome is transactional.
"""
import errno
import fcntl
import hashlib
import logging
import os
import shutil
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import BinaryIO, Iterator, Optional
from uuid import UUID

from celery import current_app
from kombu.exceptions import OperationalError as BrokerError
from rest_framework import status
from rest_framework.exceptions import APIException

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from events.models import UploadSession, VideoAsset
from events.v1.transcoding import TranscodeError, make_web_playable, partial_output_path

logger = logging.getLogger("asp_api")

FINALIZE_TASK_NAME = "events.tasks.finalize_upload_session"
CHUNK_CONTENT_TYPE = "application/offset+octet-stream"
READ_BLOCK_BYTES = 1024 * 1024
SIGNATURE_BYTES = 12
ORPHAN_GRACE_SECONDS = 3600
FINALIZE_TIMEOUT_ERROR = "finalize_timeout"
SIZE_MISMATCH_ERROR = "size_mismatch"
INVALID_SIGNATURE_ERROR = "invalid_file_signature"
CHECKSUM_MISMATCH_ERROR = "checksum_mismatch"
PROCESSING_FAILED_ERROR = "processing_failed"
QUICKTIME_ATOMS = (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip", b"pnot")
WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"


class UploadAPIError(APIException):
    """ API error carrying a machine-readable ``code`` that the upload client switches on """

    def __init__(self, code: str, detail: str, http_status: int, **extra):
        super().__init__(detail, code)
        self.status_code = http_status
        self.detail = {"code": code, "detail": detail, **extra}


@dataclass
class ChunkRequest:
    """ One chunk as received from the client: where it starts, how long it is, and where to read it from """
    offset: int
    length: int
    stream: BinaryIO
    checksum_sha256: str = ""


def upload_root() -> Path:
    """ Directory holding partial uploads, created on demand """
    root = Path(settings.RESUMABLE_UPLOAD_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def part_path(session_id: UUID) -> Path:
    """ Partial file of a session. Built from the session UUID only, never from client-supplied names """
    return upload_root() / f"{session_id}.part"


def asset_video_storage():
    """ Storage behind ``VideoAsset.video_file``, read from the field so a patched field storage is honoured """
    return VideoAsset.video_file.field.storage


def clean_display_filename(raw_name: str) -> str:
    """ Strip directories and control characters. The result is for display only and never used as a path """
    base_name = os.path.basename(raw_name.replace("\\", "/"))
    cleaned = "".join(char for char in base_name if char.isprintable()).strip()
    return "" if cleaned in (".", "..") else cleaned


def file_extension(filename: str) -> str:
    """ Lower-case extension without the dot """
    return os.path.splitext(filename)[1].lower().lstrip(".")


def final_storage_name(session: UploadSession) -> str:
    """
    Deterministic name inside the video storage, so an interrupted finalization can be resumed.

    Every upload is stored as MP4 whatever it arrived as: it is converted to H.264/AAC on the way in.
    """
    return f"{session.id}.mp4"


def has_valid_signature(header: bytes, extension: str) -> bool:
    """ Check the container magic bytes at the start of a file against its claimed extension """
    if extension in ("mp4", "mov"):
        return header[4:8] in QUICKTIME_ATOMS
    if extension == "webm":
        return header[:4] == WEBM_MAGIC
    if extension == "avi":
        return header[:4] == b"RIFF" and header[8:12] == b"AVI "
    return False


def confirmed_offset(session: UploadSession) -> int:
    """ Authoritative resume position: the committed offset, capped by what is really on disk """
    if session.status != UploadSession.UploadStatus.UPLOADING:
        return session.offset
    return min(session.offset, _actual_size(part_path(session.id)))


def _actual_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _truncate(path: Path, size: int) -> None:
    with open(path, "r+b") as handle:
        handle.truncate(size)
        handle.flush()
        os.fsync(handle.fileno())


def _truncate_quietly(path: Path, size: int) -> None:
    try:
        _truncate(path, size)
    except OSError:
        logger.exception("upload_truncate_failed size=%d", size)


def _remove_part(session_id: UUID) -> None:
    try:
        part_path(session_id).unlink(missing_ok=True)
    except OSError:
        logger.exception("upload_part_remove_failed session=%s", session_id)


def dispatch_finalization(session_id: UUID) -> bool:
    """ Queue the finalize task. A broker outage is logged, the stale-finalization sweep picks the session up later """
    try:
        current_app.send_task(FINALIZE_TASK_NAME, args=[str(session_id)])
    except BrokerError:
        logger.exception("upload_finalize_dispatch_failed session=%s", session_id)
        return False
    return True


def _lock_session(session_id: UUID, owner) -> UploadSession:
    """ Lock the owner's session row, failing fast instead of queueing behind another writer """
    queryset = UploadSession.objects.select_for_update(nowait=True)
    try:
        return get_object_or_404(queryset, pk=session_id, owner=owner)
    except OperationalError as exc:
        if getattr(exc.__cause__, "pgcode", None) != LOCK_NOT_AVAILABLE_SQLSTATE:
            raise
        raise UploadAPIError(
            "upload_in_progress", "Another request is writing to this upload.", status.HTTP_409_CONFLICT
        ) from exc


def get_session(session_id: UUID, owner) -> UploadSession:
    """ Fetch a session that belongs to ``owner``. Other users' sessions are indistinguishable from missing ones """
    return get_object_or_404(UploadSession, pk=session_id, owner=owner)


def _assert_capacity(owner, file_size: int) -> None:
    uploading = UploadSession.objects.filter(status=UploadSession.UploadStatus.UPLOADING)
    if uploading.filter(owner=owner).count() >= settings.RESUMABLE_UPLOAD_MAX_ACTIVE_PER_USER:
        raise UploadAPIError(
            "too_many_active_uploads",
            "Too many uploads are in progress. Finish or cancel one before starting another.",
            status.HTTP_409_CONFLICT,
        )
    reserved = uploading.aggregate(total=Sum(F("file_size") - F("offset")))["total"] or 0
    free = shutil.disk_usage(upload_root()).free
    if free - reserved - settings.RESUMABLE_UPLOAD_MIN_FREE_BYTES < file_size:
        raise UploadAPIError(
            "insufficient_storage", "The server does not have enough free space for this file.",
            status.HTTP_507_INSUFFICIENT_STORAGE,
        )


def _reuse_session(existing: UploadSession, validated: dict) -> UploadSession:
    states = UploadSession.UploadStatus
    checksum = validated.get("checksum_sha256", "")
    same_file = (
        existing.filename == validated["filename"]
        and existing.file_size == validated["file_size"]
        and (not checksum or checksum == existing.checksum_sha256)
    )
    lapsed = existing.status == states.UPLOADING and existing.expires_at <= timezone.now()
    reusable = existing.status in (*UploadSession.ACTIVE_STATUSES, states.COMPLETED) and not lapsed
    if not (same_file and reusable):
        raise UploadAPIError(
            "client_key_conflict", "This upload key was already used for a different or closed upload.",
            status.HTTP_409_CONFLICT,
        )
    return existing


def create_session(owner, validated: dict) -> tuple[UploadSession, bool]:
    """
    Create an upload session, or return the existing one when the same ``client_key`` is replayed.

    Returns ``(session, created)``. The active-upload limit is a soft limit: concurrent creations can overshoot it.
    """
    client_key = validated.get("client_key", "")
    if client_key:
        existing = UploadSession.objects.filter(owner=owner, client_key=client_key).first()
        if existing:
            return _reuse_session(existing, validated), False

    _assert_capacity(owner, validated["file_size"])
    expires_at = timezone.now() + timedelta(hours=settings.RESUMABLE_UPLOAD_SESSION_TTL_HOURS)
    try:
        with transaction.atomic():
            session = UploadSession.objects.create(
                owner=owner,
                client_key=client_key,
                filename=validated["filename"],
                file_size=validated["file_size"],
                checksum_sha256=validated.get("checksum_sha256", ""),
                expires_at=expires_at,
            )
    except IntegrityError:
        existing = UploadSession.objects.filter(owner=owner, client_key=client_key).first() if client_key else None
        if existing is None:
            raise
        return _reuse_session(existing, validated), False

    logger.info("upload_session_created session=%s size=%d", session.id, session.file_size)
    return session, True


def _assert_accepting_bytes(session: UploadSession) -> None:
    states = UploadSession.UploadStatus
    lapsed = session.status == states.UPLOADING and session.expires_at <= timezone.now()
    if session.status == states.EXPIRED or lapsed:
        raise UploadAPIError("session_expired", "This upload has expired.", status.HTTP_410_GONE)
    if session.status == states.CANCELLED:
        raise UploadAPIError("session_cancelled", "This upload was cancelled.", status.HTTP_410_GONE)
    if session.status != states.UPLOADING:
        raise UploadAPIError(
            "session_not_active", "This upload no longer accepts data.", status.HTTP_409_CONFLICT,
            upload_status=session.status, offset=session.offset,
        )


def _offset_mismatch(offset: int) -> UploadAPIError:
    return UploadAPIError(
        "offset_mismatch", "The upload offset does not match the server's committed offset.",
        status.HTTP_409_CONFLICT, offset=offset,
    )


def _validate_chunk_bounds(session: UploadSession, chunk: ChunkRequest) -> None:
    if chunk.length > settings.RESUMABLE_UPLOAD_MAX_CHUNK_BYTES:
        raise UploadAPIError(
            "chunk_too_large", "The chunk exceeds the maximum chunk size.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            max_chunk_size=settings.RESUMABLE_UPLOAD_MAX_CHUNK_BYTES,
        )
    if chunk.offset != session.offset:
        raise _offset_mismatch(session.offset)
    if session.offset + chunk.length > session.file_size:
        raise UploadAPIError(
            "chunk_out_of_range", "The chunk extends past the declared file size.", status.HTTP_400_BAD_REQUEST
        )


def _read_block(stream: BinaryIO, size: int) -> bytes:
    try:
        data = stream.read(size)
    except OSError as exc:
        raise UploadAPIError(
            "incomplete_chunk", "The chunk was not fully received.", status.HTTP_400_BAD_REQUEST
        ) from exc
    if not data:
        raise UploadAPIError("incomplete_chunk", "The chunk was not fully received.", status.HTTP_400_BAD_REQUEST)
    return data


def _stream_to_file(path: Path, session: UploadSession, chunk: ChunkRequest) -> str:
    """ Append the chunk at the committed offset in bounded blocks and return its SHA-256 hex digest """
    digest = hashlib.sha256()
    header = b""
    extension = file_extension(session.filename)
    with open(path, "r+b" if path.exists() else "wb") as handle:
        handle.seek(session.offset)
        handle.truncate()
        remaining = chunk.length
        while remaining:
            data = _read_block(chunk.stream, min(READ_BLOCK_BYTES, remaining))
            if session.offset == 0 and len(header) < SIGNATURE_BYTES:
                header += data[:SIGNATURE_BYTES - len(header)]
                if len(header) == SIGNATURE_BYTES and not has_valid_signature(header, extension):
                    raise UploadAPIError(
                        INVALID_SIGNATURE_ERROR, "The file content does not match its extension.",
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                    )
            handle.write(data)
            digest.update(data)
            remaining -= len(data)
        handle.flush()
        os.fsync(handle.fileno())
    return digest.hexdigest()


def _write_chunk(session: UploadSession, chunk: ChunkRequest) -> None:
    """ Persist one chunk durably or leave the partial file exactly at the committed offset """
    path = part_path(session.id)
    try:
        digest = _stream_to_file(path, session, chunk)
        if chunk.checksum_sha256 and digest != chunk.checksum_sha256:
            raise UploadAPIError(
                CHECKSUM_MISMATCH_ERROR, "The chunk checksum does not match its content.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
    except UploadAPIError:
        _truncate_quietly(path, session.offset)
        raise
    except OSError as exc:
        _truncate_quietly(path, session.offset)
        if exc.errno == errno.ENOSPC:
            raise UploadAPIError(
                "insufficient_storage", "The server ran out of storage space.", status.HTTP_507_INSUFFICIENT_STORAGE
            ) from exc
        raise


def _commit_chunk(session: UploadSession, chunk: ChunkRequest) -> None:
    _write_chunk(session, chunk)
    session.offset += chunk.length
    session.expires_at = timezone.now() + timedelta(hours=settings.RESUMABLE_UPLOAD_SESSION_TTL_HOURS)
    if session.offset == session.file_size:
        session.status = UploadSession.UploadStatus.FINALIZING
    session.save(update_fields=["offset", "expires_at", "status", "modified"])
    if session.status == UploadSession.UploadStatus.FINALIZING:
        transaction.on_commit(partial(dispatch_finalization, session.id))


def append_chunk(session_id: UUID, owner, chunk: ChunkRequest) -> UploadSession:
    """
    Append a chunk at the committed offset.

    The partial file is reconciled with the committed offset first: bytes beyond it (a write that crashed before its
    commit) are truncated, and a file shorter than the offset (lost data) lowers the offset and reports a mismatch so
    the client resumes from the truth.
    """
    lowered_to = None
    with transaction.atomic():
        session = _lock_session(session_id, owner)
        _assert_accepting_bytes(session)
        path = part_path(session.id)
        actual = _actual_size(path)
        if actual < session.offset:
            logger.error("upload_data_loss session=%s committed=%d on_disk=%d", session.id, session.offset, actual)
            session.offset = lowered_to = actual
            session.save(update_fields=["offset", "modified"])
        elif actual > session.offset:
            _truncate(path, session.offset)
        if lowered_to is None:
            _validate_chunk_bounds(session, chunk)
            _commit_chunk(session, chunk)
    if lowered_to is not None:
        raise _offset_mismatch(lowered_to)
    return session


def _discard_unused_asset(session: UploadSession) -> None:
    """
    Delete the asset a completed upload produced, together with its video and thumbnail files.

    The asset row is locked like Event creation locks it, so a concurrent publish either wins (and the removal is
    refused here) or loses (and is rejected because the asset is gone). An asset an event already uses is kept.
    """
    asset = VideoAsset.objects.select_for_update().filter(pk=session.video_asset_id).first()
    if asset is None:
        return
    if asset.event_id is not None:
        raise UploadAPIError(
            "video_in_use", "This video is already used by a session and cannot be removed here.",
            status.HTTP_409_CONFLICT, upload_status=session.status,
        )
    _discard_failed_asset(asset)
    session.video_asset = None


def cancel_session(session_id: UUID, owner) -> UploadSession:
    """
    Cancel an upload and discard what it left on disk. Already closed sessions are a no-op.

    An in-progress upload loses its partial file. A completed one loses its asset and video, unless an event
    already uses that asset, which is refused with a 409.
    """
    states = UploadSession.UploadStatus
    with transaction.atomic():
        session = _lock_session(session_id, owner)
        if session.status in (states.CANCELLED, states.EXPIRED, states.FAILED):
            return session
        if session.status == states.COMPLETED:
            _discard_unused_asset(session)
        elif session.status != states.UPLOADING:
            raise UploadAPIError(
                "session_not_active", "This upload can no longer be cancelled.", status.HTTP_409_CONFLICT,
                upload_status=session.status,
            )
        session.status = states.CANCELLED
        session.save(update_fields=["status", "video_asset", "modified"])
        transaction.on_commit(partial(_remove_part, session.id))
    logger.info("upload_session_cancelled session=%s", session.id)
    return session


def retry_finalization(session_id: UUID, owner) -> UploadSession:
    """ Re-queue finalization for a session whose last chunk was committed. Safe to call repeatedly """
    session = get_session(session_id, owner)
    if session.status == UploadSession.UploadStatus.FINALIZING:
        if not dispatch_finalization(session.id):
            raise UploadAPIError(
                "queue_unavailable", "Finalization could not be queued. Try again shortly.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
    elif session.status != UploadSession.UploadStatus.COMPLETED:
        raise UploadAPIError(
            "session_not_finalizable", "This upload is not waiting to be finalized.", status.HTTP_409_CONFLICT,
            upload_status=session.status,
        )
    return session


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(partial(handle.read, READ_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _verification_failure(session: UploadSession, source: Optional[Path]) -> str:
    """ Error code describing why the assembled file is unusable, or an empty string when it is sound """
    if source is None:
        logger.error(
            "upload_file_missing session=%s expected=%d part_root=%s", session.id, session.file_size, upload_root()
        )
        return SIZE_MISMATCH_ERROR
    if source.stat().st_size != session.file_size:
        logger.error(
            "upload_size_mismatch session=%s expected=%d on_disk=%d", session.id, session.file_size,
            source.stat().st_size,
        )
        return SIZE_MISMATCH_ERROR
    with open(source, "rb") as handle:
        if not has_valid_signature(handle.read(SIGNATURE_BYTES), file_extension(session.filename)):
            return INVALID_SIGNATURE_ERROR
    if session.checksum_sha256 and _hash_file(source) != session.checksum_sha256:
        return CHECKSUM_MISMATCH_ERROR
    return ""


def _fail_session(session: UploadSession, error_code: str) -> None:
    session.status = UploadSession.UploadStatus.FAILED
    session.error_code = error_code
    session.save(update_fields=["status", "error_code", "modified"])
    transaction.on_commit(partial(_remove_part, session.id))
    logger.error("upload_session_failed session=%s reason=%s", session.id, error_code)


def _remove_video_file(storage_name: str) -> None:
    try:
        Path(asset_video_storage().path(storage_name)).unlink(missing_ok=True)
    except OSError:
        logger.exception("upload_video_remove_failed name=%s", storage_name)


def _remove_promoted_file(session: UploadSession) -> None:
    """ Drop the converted file and any half-written conversion a failed finalization left in the video storage """
    destination = Path(asset_video_storage().path(final_storage_name(session)))
    for leftover in (destination, partial_output_path(destination)):
        _remove_video_file(leftover.name)


def _remove_thumbnail(thumbnail_name: str) -> None:
    try:
        VideoAsset.thumbnail.field.storage.delete(thumbnail_name)
    except OSError:
        logger.exception("upload_thumbnail_remove_failed name=%s", thumbnail_name)


def _discard_failed_asset(asset: VideoAsset) -> None:
    """ Delete an asset row and, once committed, its video and thumbnail files """
    video_name = asset.video_file.name
    thumbnail_name = asset.thumbnail.name
    asset.delete()
    if video_name:
        transaction.on_commit(partial(_remove_video_file, video_name))
    if thumbnail_name:
        transaction.on_commit(partial(_remove_thumbnail, thumbnail_name))


@contextmanager
def _finalization_claim(session_id: UUID) -> Iterator[bool]:
    """
    Claim the right to convert a session's file while the block runs; yields False when another worker holds it.

    A conversion lasts hours, far too long for a transaction or a row lock: an idle-in-transaction timeout or a
    connection pooler would kill it, and the owner's cancel and the stale-finalization sweep would be blocked or blind
    meanwhile. An exclusive ``flock`` on the partial file keeps two workers (a redelivered task, the sweep's
    re-queue) from writing the same output instead. The kernel drops it when the process dies, so a crashed worker
    never blocks the retry. Without a partial file there is nothing to convert and the claim is granted.
    """
    with ExitStack() as stack:
        claimed = True
        try:
            handle = stack.enter_context(open(part_path(session_id), "r+b"))
        except FileNotFoundError:
            pass
        else:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                claimed = False
        yield claimed


def _prepare_video(session: UploadSession) -> str:
    """
    Verify the uploaded bytes and leave a browser-playable MP4 under the final name. Returns an error code or "".

    The partial file is removed once the MP4 exists. If a previous attempt got that far and died before the commit,
    only the MP4 is left, which is trusted as it is: it is only ever renamed into place when complete.
    """
    part = part_path(session.id)
    has_part = part.exists()
    destination = Path(asset_video_storage().path(final_storage_name(session)))
    if not has_part and destination.exists():
        return ""

    source = part if has_part else None
    failure = _verification_failure(session, source)
    if failure:
        return failure
    try:
        make_web_playable(part, destination)
    except TranscodeError:
        logger.exception("upload_conversion_failed session=%s", session.id)
        return PROCESSING_FAILED_ERROR
    part.unlink(missing_ok=True)
    return ""


def _create_asset(session: UploadSession, storage_name: str) -> VideoAsset:
    """ Create the asset for a converted file: READY once a duration was found, otherwise FAILED """
    return VideoAsset.create_with_status(os.path.splitext(session.filename)[0][:255], storage_name)


def _register_asset(session: UploadSession) -> str:
    """ Create the asset for the converted file and complete the session. Returns an error code or "" """
    asset = _create_asset(session, final_storage_name(session))
    if asset.status != VideoAsset.VideoStatus.READY:
        _discard_failed_asset(asset)
        return PROCESSING_FAILED_ERROR
    session.video_asset = asset
    session.status = UploadSession.UploadStatus.COMPLETED
    session.save(update_fields=["video_asset", "status", "modified"])
    return ""


def _settle_finalization(session_id: UUID, failure: str) -> Optional[UploadSession]:
    """
    Record the outcome of a conversion in one short transaction, after checking the session still waits for it.

    The session may have been settled while the conversion ran: another worker completed it, or the stuck-session
    sweep failed it. A completed one owns the converted file; for any other state the file is an orphan and goes.
    """
    with transaction.atomic():
        session = UploadSession.objects.select_for_update().filter(pk=session_id).first()
        if session is None:
            return None
        if session.status != UploadSession.UploadStatus.FINALIZING:
            if session.status != UploadSession.UploadStatus.COMPLETED:
                transaction.on_commit(partial(_remove_promoted_file, session))
            return session

        failure = failure or _register_asset(session)
        if failure:
            _fail_session(session, failure)
    return session


def finalize_session(session_id: UUID) -> Optional[UploadSession]:
    """
    Verify, convert and register a fully uploaded file. Idempotent and safe under concurrent or repeated calls.

    Three steps, with no transaction open while the file is verified and converted (see ``_finalization_claim``):
    read the session, convert under the file claim, then settle the outcome in one short transaction. The asset row is
    created in that transaction together with the session update, so a crash before the commit rolls the row back, and
    because the converted file keeps a deterministic name the retry picks up where the crash happened.
    Returns None when the session does not exist or another worker is converting its file.
    """
    session = UploadSession.objects.filter(pk=session_id).first()
    if session is None or session.status != UploadSession.UploadStatus.FINALIZING:
        return session

    with _finalization_claim(session.id) as claimed:
        if not claimed:
            return None
        failure = _prepare_video(session)
        settled = _settle_finalization(session.id, failure)

    if settled is not None:
        logger.info("upload_session_finalized session=%s result=%s", settled.id, settled.status)
    return settled


def _expire_sessions(now) -> int:
    expired = 0
    stale = UploadSession.objects.filter(status=UploadSession.UploadStatus.UPLOADING, expires_at__lte=now)
    for session_id in list(stale.values_list("pk", flat=True)):
        with transaction.atomic():
            session = UploadSession.objects.select_for_update(skip_locked=True).filter(
                pk=session_id, status=UploadSession.UploadStatus.UPLOADING, expires_at__lte=now
            ).first()
            if session is None:
                continue
            session.status = UploadSession.UploadStatus.EXPIRED
            session.save(update_fields=["status", "modified"])
            transaction.on_commit(partial(_remove_part, session.id))
            expired += 1
    return expired


def _fail_stuck_finalizations(now) -> int:
    """ Fail sessions that stayed FINALIZING past the deadline, so a poison session is not re-queued forever """
    cutoff = now - timedelta(hours=settings.RESUMABLE_UPLOAD_FINALIZE_TIMEOUT_HOURS)
    stuck = UploadSession.objects.filter(status=UploadSession.UploadStatus.FINALIZING, modified__lte=cutoff)
    failed = 0
    for session_id in list(stuck.values_list("pk", flat=True)):
        with transaction.atomic():
            session = UploadSession.objects.select_for_update(skip_locked=True).filter(
                pk=session_id, status=UploadSession.UploadStatus.FINALIZING, modified__lte=cutoff
            ).first()
            if session is None:
                continue
            _fail_session(session, FINALIZE_TIMEOUT_ERROR)
            transaction.on_commit(partial(_remove_promoted_file, session))
            failed += 1
    return failed


def _redispatch_stalled_finalizations(now) -> int:
    cutoff = now - timedelta(minutes=settings.RESUMABLE_UPLOAD_FINALIZE_STALE_MINUTES)
    stalled = UploadSession.objects.filter(status=UploadSession.UploadStatus.FINALIZING, modified__lte=cutoff)
    redispatched = 0
    for session_id in list(stalled.values_list("pk", flat=True)):
        redispatched += dispatch_finalization(session_id)
    return redispatched


def _purge_old_sessions(now) -> int:
    cutoff = now - timedelta(days=settings.RESUMABLE_UPLOAD_RETENTION_DAYS)
    old = UploadSession.objects.filter(status__in=UploadSession.TERMINAL_STATUSES, modified__lte=cutoff)
    for session_id in list(old.values_list("pk", flat=True)):
        _remove_part(session_id)
    deleted, _ = old.delete()
    return deleted


def _remove_orphan_parts(now) -> int:
    """ Delete partial files that no active session owns, e.g. left behind by a crash after a state change """
    active_ids = {str(pk) for pk in UploadSession.objects.filter(
        status__in=UploadSession.ACTIVE_STATUSES
    ).values_list("pk", flat=True)}
    removed = 0
    for path in upload_root().glob("*.part"):
        if path.stem in active_ids:
            continue
        try:
            if now.timestamp() - path.stat().st_mtime < ORPHAN_GRACE_SECONDS:
                continue
            path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
        except OSError:
            logger.exception("upload_orphan_remove_failed file=%s", path.name)
            continue
        removed += 1
    return removed


def cleanup_sessions() -> dict:
    """ Expire abandoned sessions, fail or restart stalled finalizations, purge old rows, sweep orphaned files """
    now = timezone.now()
    summary = {
        "expired": _expire_sessions(now),
        "finalizations_failed": _fail_stuck_finalizations(now),
        "finalizations_redispatched": _redispatch_stalled_finalizations(now),
        "purged": _purge_old_sessions(now),
        "orphan_files_removed": _remove_orphan_parts(now),
    }
    logger.info("upload_cleanup %s", " ".join(f"{key}={value}" for key, value in summary.items()))
    return summary
