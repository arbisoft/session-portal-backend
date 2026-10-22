"""
Resumable upload helpers.

Protocol: the client creates an ``UploadSession`` and then PATCHes consecutive chunks to it. Each chunk is appended to
a partial file at exactly ``session.offset`` and the new offset is committed with the same row lock that guarded the
write, so the committed offset only ever names bytes that were fsynced. A crash between the write and the commit
leaves surplus bytes behind the committed offset, which the next writer truncates away.

When the last byte is committed the session moves to ``FINALIZING`` and a Celery task verifies the file, promotes it to
the video storage and creates the ``VideoAsset``. Every step of that task is safe to run again.
"""
import errno
import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import BinaryIO, Optional
from uuid import UUID

from celery import current_app
from kombu.exceptions import OperationalError as BrokerError
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from events.models import ALLOWED_VIDEO_EXTENSIONS, UploadSession, VideoAsset

logger = logging.getLogger("asp_api")

FINALIZE_TASK_NAME = "events.tasks.finalize_upload_session"
CHUNK_CONTENT_TYPE = "application/offset+octet-stream"
READ_BLOCK_BYTES = 1024 * 1024
SIGNATURE_BYTES = 12
ORPHAN_GRACE_SECONDS = 3600
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


def validate_video_extension(filename: str) -> str:
    """ Return ``filename`` unchanged if it has a supported video extension, otherwise raise a validation error """
    extension = file_extension(filename)
    if extension not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '.{extension}'. Allowed formats: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}."
        )
    return filename


def final_storage_name(session: UploadSession) -> str:
    """ Deterministic name inside the video storage, so an interrupted finalization can be resumed """
    return f"{session.id}.{file_extension(session.filename)}"


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
                        "invalid_file_signature", "The file content does not match its extension.",
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
                "checksum_mismatch", "The chunk checksum does not match its content.",
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


def cancel_session(session_id: UUID, owner) -> UploadSession:
    """ Cancel an in-progress upload and discard its partial file. Already closed sessions are a no-op """
    states = UploadSession.UploadStatus
    with transaction.atomic():
        session = _lock_session(session_id, owner)
        if session.status in (states.CANCELLED, states.EXPIRED, states.FAILED):
            return session
        if session.status != states.UPLOADING:
            raise UploadAPIError(
                "session_not_active", "This upload can no longer be cancelled.", status.HTTP_409_CONFLICT,
                upload_status=session.status,
            )
        session.status = states.CANCELLED
        session.save(update_fields=["status", "modified"])
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


def _source_file(session: UploadSession) -> Optional[Path]:
    """ Where the finished bytes are: the partial file, or the promoted file if a previous attempt already moved it """
    for candidate in (part_path(session.id), Path(asset_video_storage().path(final_storage_name(session)))):
        if candidate.exists():
            return candidate
    return None


def _verification_failure(session: UploadSession, source: Optional[Path]) -> str:
    """ Error code describing why the assembled file is unusable, or an empty string when it is sound """
    if source is None or source.stat().st_size != session.file_size:
        return "size_mismatch"
    with open(source, "rb") as handle:
        if not has_valid_signature(handle.read(SIGNATURE_BYTES), file_extension(session.filename)):
            return "invalid_file_signature"
    if session.checksum_sha256 and _hash_file(source) != session.checksum_sha256:
        return "checksum_mismatch"
    return ""


def _fail_session(session: UploadSession, error_code: str) -> None:
    session.status = UploadSession.UploadStatus.FAILED
    session.error_code = error_code
    session.save(update_fields=["status", "error_code", "modified"])
    _remove_part(session.id)
    logger.error("upload_session_failed session=%s reason=%s", session.id, error_code)


def _promote_file(session: UploadSession, source: Path) -> str:
    """ Move the finished file into the video storage under its deterministic name """
    name = final_storage_name(session)
    destination = Path(asset_video_storage().path(name))
    if source != destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    return name


def _create_asset(session: UploadSession, storage_name: str) -> VideoAsset:
    """ Create the asset as ``VideoAssetCreateSerializer`` does: PROCESSING, then READY once a duration was found """
    title = os.path.splitext(session.filename)[0][:255]
    asset = VideoAsset.objects.create(title=title, video_file=storage_name, status=VideoAsset.VideoStatus.PROCESSING)
    asset.status = VideoAsset.VideoStatus.READY if asset.duration > 0 else VideoAsset.VideoStatus.FAILED
    VideoAsset.objects.filter(pk=asset.pk).update(status=asset.status)
    return asset


def finalize_session(session_id: UUID) -> Optional[UploadSession]:
    """
    Verify, promote and register a fully uploaded file. Idempotent and safe under concurrent or repeated calls.

    The row lock is skipped rather than awaited, so a second worker returns immediately while the first one works.
    The asset row is created in the same transaction that completes the session: a crash before the commit rolls the
    row back, and because the promoted file keeps a deterministic name the retry picks up where the crash happened.
    Returns None when the session does not exist or is being finalized elsewhere.
    """
    with transaction.atomic():
        session = UploadSession.objects.select_for_update(skip_locked=True).filter(pk=session_id).first()
        if session is None or session.status != UploadSession.UploadStatus.FINALIZING:
            return session

        source = _source_file(session)
        failure = _verification_failure(session, source)
        if failure:
            _fail_session(session, failure)
            return session

        asset = _create_asset(session, _promote_file(session, source))
        session.video_asset = asset
        if asset.status == VideoAsset.VideoStatus.READY:
            session.status = UploadSession.UploadStatus.COMPLETED
        else:
            session.status = UploadSession.UploadStatus.FAILED
            session.error_code = "processing_failed"
        session.save(update_fields=["video_asset", "status", "error_code", "modified"])

    logger.info("upload_session_finalized session=%s result=%s", session.id, session.status)
    return session


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
        except FileNotFoundError:
            continue
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def cleanup_sessions() -> dict:
    """ Expire abandoned sessions, restart stalled finalizations, purge old rows and sweep orphaned partial files """
    now = timezone.now()
    summary = {
        "expired": _expire_sessions(now),
        "finalizations_redispatched": _redispatch_stalled_finalizations(now),
        "purged": _purge_old_sessions(now),
        "orphan_files_removed": _remove_orphan_parts(now),
    }
    logger.info("upload_cleanup %s", " ".join(f"{key}={value}" for key, value in summary.items()))
    return summary
