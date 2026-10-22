# Resumable video uploads

Staff upload large videos (default limit 20 GiB) in small chunks. Progress is stored on the server, so a dropped connection, a browser refresh or a server restart only costs the chunk that was in flight.

The older single-request upload is the same `POST /api/v1/events/videoassets/` with a `multipart/form-data` body and is unchanged. A JSON body on that endpoint creates a resumable session instead.

## Protocol

An application-managed offset protocol modelled on [tus](https://tus.io/protocols/resumable-upload) (`Upload-Offset`, `application/offset+octet-stream`, `Upload-Checksum`). It is **not** a conforming tus server: it has no `HEAD`/`OPTIONS` discovery and uses JSON responses. The stack has no object storage (files live on a shared media volume) and requests pass through the Next.js BFF, so a small, explicit protocol was chosen over adding a tus dependency.

All endpoints are under `/api/v1/events/videoassets/`, the same path as the single-request upload, require a JWT, and are staff-only (`IsStaffPermission`). A session belongs to the user who created it; anyone else gets `404`.

| Method and path | Purpose |
| --- | --- |
| `POST /videoassets/` (JSON body) | Create a session. Body: `filename`, `file_size`, optional `checksum_sha256` (hex), optional `client_key` (8-64 chars `[A-Za-z0-9_-]`). `201`, or `200` with the existing session when the same `client_key` is replayed with the same `filename` and `file_size`. A replay that supplies a `checksum_sha256` must match the stored one; a session created without a checksum cannot be replayed with one (`409 client_key_conflict`), so a `200` never implies whole-file verification that will not happen. A replay without a checksum is accepted and keeps the stored one. |
| `GET /videoassets/<id>/` | Authoritative status. `offset` is the number of contiguous bytes to **not** send again. Also sent as the `Upload-Offset` header. |
| `PATCH /videoassets/<id>/` | Append one chunk. Headers: `Content-Type: application/offset+octet-stream`, `Content-Length`, `Upload-Offset` (must equal the server offset), optional `Upload-Checksum: sha256 <base64>`. Body is the raw bytes. |
| `DELETE /videoassets/<id>/` | Cancel and delete the partial file. Idempotent. `409` once the last byte has arrived; cancelling a session that is already cancelled, expired or failed is a no-op (`204`). |
| `POST /videoassets/<id>/finalize/` | Re-queue finalization (`202`, or `503 queue_unavailable` if the broker is down). Idempotent. Only needed if the task was lost. `409 session_not_finalizable` unless the session is `FINALIZING` or `COMPLETED`. |

Session representation: `id`, `filename`, `file_size`, `offset`, `upload_status`, `error_code`, `video_asset_id`, `expires_at`, `chunk_size` (recommended), `max_chunk_size`.

`upload_status`: `UPLOADING` → `FINALIZING` → `COMPLETED`, or `FAILED` / `CANCELLED` / `EXPIRED`. Only `COMPLETED` means the video is registered and `video_asset_id` is usable. `FINALIZING` means every byte arrived but the file is still being verified and probed.

Errors are `{"code": ..., "detail": ...}` plus context. Codes the client acts on:

| Status | `code` | Meaning |
| --- | --- | --- |
| 409 | `offset_mismatch` (`offset`) | The chunk does not start at the server offset. Resume from `offset`. |
| 409 | `upload_in_progress` | Another request is writing this session. Retry shortly. |
| 409 | `session_not_active` (`upload_status`) | Already finalizing, completed or failed. |
| 409 | `session_not_finalizable` (`upload_status`) | `finalize` was called for an upload that is not waiting for it. |
| 409 | `too_many_active_uploads`, `client_key_conflict` | Limits at creation. |
| 410 | `session_expired`, `session_cancelled` | Start a new upload. |
| 413 | `chunk_too_large` | Larger than `max_chunk_size`. |
| 400 | `incomplete_chunk`, `chunk_out_of_range` | Body shorter than `Content-Length`, or beyond the declared file size. |
| 415 | `unsupported_media_type` | Wrong `Content-Type`. |
| 422 | `checksum_mismatch`, `invalid_file_signature` | Corrupted chunk, or the first bytes are not a video of the claimed type. |
| 507 | `insufficient_storage` | Not enough disk space, at creation or while writing a chunk. |
| 503 | `queue_unavailable` | The broker is down, so finalization was not queued. Retry `finalize` shortly. |
| 429 | (throttle) | Honour `Retry-After`. |

## Durability and recovery

- The committed `offset` only advances after the chunk was written and `fsync`ed, in the same transaction that holds a row lock (`SELECT ... FOR UPDATE NOWAIT`) taken before the write. Concurrent writers get `upload_in_progress`; they cannot interleave.
- A chunk is all-or-nothing. If the body is cut short, a checksum fails or the disk is full, the partial file is truncated back to the committed offset. At most one chunk is re-sent after a failure.
- Crash after the write but before the commit: the file is longer than the committed offset. The next writer truncates the surplus. The client is never told those bytes were accepted.
- Metadata ahead of disk (partial file lost or shortened): `GET` reports `min(committed offset, bytes on disk)`, and the next `PATCH` lowers the stored offset and answers `offset_mismatch` with the true value.
- Lost acknowledgement: the chunk is committed, the client did not hear. Its retry gets `409 offset_mismatch` with the new offset, and the client continues from there. Bytes are never appended twice.
- Finalization (Celery task `events.tasks.finalize_upload_session`) checks the size, the container signature and, if given, the whole-file SHA-256; moves the file to `videos/<session id>.<ext>`; creates the `VideoAsset` (`READY` when ffmpeg finds a duration, otherwise the session fails with `processing_failed`). It is idempotent: the destination name is deterministic, the asset row and the session update commit together, and concurrent runs skip a locked row. Storage errors are retried with backoff; if a worker dies, `cleanup_upload_sessions` re-queues sessions stuck in `FINALIZING`.
- Failed verification (`size_mismatch`, `checksum_mismatch`, `invalid_file_signature`) deletes the partial file and fails the session; the client must start a new one.

## Security

- Session ids are random UUIDs; access is limited to the owner, other users see `404`.
- The client filename is display-only (directories and control characters stripped). Storage paths are built from the session UUID, never from user input.
- Extension allow-list (`mp4`, `mov`, `avi`, `webm`), magic-byte check on the first chunk and again at finalization, size cap, per-user active-session cap, free-space check that also accounts for space promised to other sessions.
- Throttle scopes `upload_create` (30/hour), `upload_chunk` (2000/min), `upload_status` (600/min) in `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`. The counters use Django's cache; with several instances configure a shared cache or the limits apply per process.
- Nothing logs file contents, tokens or filenames. Log lines carry the session id (`upload_session_created`, `upload_session_finalized`, `upload_session_failed`, `upload_data_loss`, `upload_cleanup`, ...).
- Not implemented: virus scanning or quarantine (none exists in the product today).

## Settings

All read from the environment (see `settings/base.py`).

| Variable | Default | Notes |
| --- | --- | --- |
| `RESUMABLE_UPLOAD_ROOT` | `MEDIA_ROOT/uploads` | Partial files. Must be shared by every web and Celery worker, and should be on the same filesystem as `MEDIA_ROOT/videos` so promotion is a rename. Do not serve it publicly. |
| `RESUMABLE_UPLOAD_MAX_FILE_BYTES` | 20 GiB | Keep the frontend `MAX_VIDEO_FILE_SIZE_BYTES` equal. |
| `RESUMABLE_UPLOAD_CHUNK_BYTES` | 8 MiB | Recommended chunk size, returned to the client. |
| `RESUMABLE_UPLOAD_MAX_CHUNK_BYTES` | 16 MiB | Hard per-request cap. |
| `RESUMABLE_UPLOAD_SESSION_TTL_HOURS` | 72 | Sliding: every committed chunk extends it. |
| `RESUMABLE_UPLOAD_MAX_ACTIVE_PER_USER` | 3 | Soft limit. |
| `RESUMABLE_UPLOAD_MIN_FREE_BYTES` | 1 GiB | Free space kept in reserve. An upload is refused (`507 insufficient_storage`) unless free space, minus space promised to other sessions, minus this reserve, exceeds the file size. Raise it on production hosts. |
| `RESUMABLE_UPLOAD_FINALIZE_STALE_MINUTES` | 30 | A `FINALIZING` session older than this is re-queued by the sweep. |
| `RESUMABLE_UPLOAD_RETENTION_DAYS` | 7 | Closed sessions are purged after this. |

## Cleanup

`python manage.py cleanup_upload_sessions` (or the Celery task `events.tasks.cleanup_upload_sessions`) expires sessions past their TTL, re-queues stalled finalizations, deletes old closed rows and removes partial files that no active session owns (older than one hour). **Nothing in the repository schedules it**: run it hourly from cron or Celery beat.

## Infrastructure limits to check

The repository contains no reverse-proxy or production server configuration, so these could not be verified here:

- Reverse proxy / ingress: request body limit of at least `RESUMABLE_UPLOAD_MAX_CHUNK_BYTES` (nginx `client_max_body_size 16m;` or more). nginx's default of 1 MB rejects every chunk. A 20 GiB limit is no longer needed.
- Application server: a request timeout long enough for one chunk at the slowest expected uplink (an 8 MiB chunk at 1 Mbit/s takes about 70 s). Django reads the body in 1 MiB blocks and never buffers a chunk in memory.
- Disk: free space of at least the largest expected upload plus `RESUMABLE_UPLOAD_MIN_FREE_BYTES`, on the volume holding `RESUMABLE_UPLOAD_ROOT` and `MEDIA_ROOT`.
- Celery: a worker must run (it was previously only needed for Drive imports) and must mount the same volume as the web containers. In `docker-compose.yml` both already mount `./media`.

## Known limitations

- Finalization re-reads the file once when a whole-file checksum was supplied (and ffmpeg reads it again), so a 20 GiB file takes minutes after the last chunk. The UI shows a "processing" state.
- The active-session limit and the free-space check are not transactional; simultaneous creations can overshoot slightly.
- Chunks are sequential per session. Parallel part uploads are not supported.
- The partial file is written through the application server, not directly to object storage.
