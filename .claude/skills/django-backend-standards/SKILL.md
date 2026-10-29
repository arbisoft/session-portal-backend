---
name: django-backend-standards
description: Django/DRF coding rules for the Sessions Portal backend — views, serializers, filters, models, settings, and project traps (ffmpeg on save, slug signal, storages). Used by backend-agent when building models, views, serializers, and APIs. For migration rules see django-migration-standards.
---

# Django Backend Standards

## Coding rules

- Request flow lives in views; shared logic in `<app>/v1/utils.py`, model methods, or queryset helpers. No `services.py` by default.
- Serializers in `<app>/v1/serializers.py`; filters in `<app>/v1/filters.py`; routes in `<app>/v1/urls.py`.
- Generic DRF views for CRUD (`ListAPIView`, `CreateAPIView`, `ListCreateAPIView`), `APIView` for one-off endpoints.
- Per-method permissions via `get_permissions()` (see `TagListView`: GET open to authenticated users, POST staff-only).
- `snake_case` for Python names; max 120 characters per line.
- Descriptive names: no `r`, `qs`, `fn`; lambda parameters are named too.
- Type hints on new functions; docstrings on models and non-trivial helpers.
- Keep functions under pylint limits (`max-args = 5`, `max-locals = 15`, `max-branches = 12`). Flatten with helpers and early returns.

## New endpoint checklist

1. Serializer(s): separate list/detail/create when field sets differ; `read_only_fields`; business rules in `validate()`.
2. View: queryset with the `select_related`/`prefetch_related` the serializer needs; `get_object_or_404`; correct permissions (global `IsAuthenticated`, plus `IsStaffPermission` for staff-only).
3. Route in `<app>/v1/urls.py`.
4. Filter via `django_filters` `FilterSet` for list params.
5. Tests in `<app>/tests/` (see `.claude/rules/testing.md`).

## ORM and query optimization

Follow `.claude/skills/django-query-optimisation/SKILL.md` (N+1 prevention, `select_related` / `prefetch_related` / `Prefetch`, bulk lookup maps, serializer context).

Project specifics:

- Event serializers walk `creator` (FK), `tags` / `playlists` / `presenters` (M2M), and `videos` (reverse FK from `VideoAsset.event`; an event can have several). Every new field there needs matching `select_related` / `prefetch_related`.
- Remember `.first()` and `.filter()` on a related manager hit the DB even when prefetched.
- Tags and playlists are ordered by most recent event time — don't override ordering without checking those querysets.
- List endpoint returns only events with at least one video; keep that filter when changing `EventsListView`.

## Project traps

- **`VideoAsset.save()` runs ffmpeg synchronously** whenever `video_file` is set (saves, probes duration, extracts a thumbnail at ~20% of duration, saves again). Use `QuerySet.update()` for other columns. ffmpeg errors are logged, not raised; `duration == 0` means failed.
- **Event slugs** are set by the `post_save` signal in `events/signals.py`, appending the id on a duplicate title. Do not set them in views or serializers.
- **Storages** (`videos/`, `thumbnails/`, `captions/`) are module-level `FileSystemStorage` instances built from `MEDIA_ROOT` at import time in `events/models.py`.
- **`on_delete=DO_NOTHING`** on `Event` FKs and a deletion-disabled `EventAdmin`: don't add cascading deletes.
- **Google login** is gated by `hd` ∈ {`arbisoft.com`, `edly.io`} while `ALLOW_ONLY_INTERNAL_USERS` is true.

## Settings

- `settings/base.py` reads `.env` via python-dotenv and ends with `from .local import *` (silently ignored if missing). `settings/local.py` is gitignored; `local.example.py` is the template.
- New configuration: read from the environment in `base.py` with a safe default, and add the key to `local.example.py` and the README setup notes so a fresh checkout boots.
- Never put secrets in `base.py`. `DJANGO_SECRET_KEY` and OAuth credentials come from the environment.
- `settings/test.py` is test-only (migrations disabled, `memory://` Celery broker, `DB_*` env vars). Don't import it from app code.

## Logging

- Logger name `asp_api` (`logging.getLogger("asp_api")`); the only logger with handlers configured (console, `api.log`, `api_error.log`, mail_admins).
- Use `logger.exception(...)` in `except` blocks.

## Migrations

Follow `.claude/skills/django-migration-standards/SKILL.md`.
