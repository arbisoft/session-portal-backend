# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Django 4.2 + DRF backend for Arbisoft's internal "Sessions Portal" (recorded sessions/events with video, tags, playlists, presenters). Python 3.12, PostgreSQL required (uses `django.contrib.postgres` trigram search, so SQLite won't work). Celery + Redis are used for Google Drive video imports and for finalizing resumable uploads.

## Commands

```bash
# Setup (README.md has the full macOS walkthrough)
cp arbisoft_sessions_portal/settings/local.example.py arbisoft_sessions_portal/settings/local.py  # gitignored
pip install -r requirements/base.txt -r requirements/dev.txt   # dev.txt does NOT include base.txt
python manage.py migrate
python manage.py runserver

# Tests (settings: arbisoft_sessions_portal.settings.test, needs a reachable Postgres)
pytest --cov --cov-report=term                                  # CI command; coverage must stay >= 80%
pytest events/tests/test_apis.py::TestClassName::test_name      # single test
pytest -k "search"                                              # by keyword

# Lint (this is exactly what CI runs: pylint + pycodestyle + isort --check over `events users`)
tox -e quality
tox -e isort                                                    # auto-fix import ordering

# Docker (django + db + redis + celery; entrypoint.sh runs migrate; in bash UID is read-only: `export UID` instead)
export GID=$(id -g) UID=$(id -u) && docker-compose up --build
docker-compose --profile dev up lint
docker-compose --profile dev up test

# Celery worker (needed for Google Drive downloads and resumable-upload finalization)
celery -A arbisoft_sessions_portal worker -l info

# Management commands (events/management/commands/)
python manage.py check_videoasset_status --recent 24 --processing   # status of video assets
python manage.py prepopulate_events data.csv --dry-run              # CSV import; queues Drive downloads on Celery
```

API docs are served at `/api/docs/` (Swagger) and `/api/redoc/`.

## Architecture

Two Django apps, both exposing a versioned API under `/api/v1/<app>/` with a `v1/` subpackage holding that app's `serializers.py`, `views.py`, `urls.py` (plus `filters.py`, `pagination.py`, `utils.py` in `events`). New API versions should be a sibling package, not edits to `v1`.

- **`users`** — has no models; uses `django.contrib.auth.User`. Provides login (Google OAuth access token → JWT via `GoogleUserInfoService`, or email/password → JWT) and staff-only user search. `users/permissions.py::IsStaffPermission` is the shared gate for staff-only endpoints, including ones in `events`. Google login rejects accounts whose `hd` isn't `arbisoft.com`/`edly.io` while `ALLOW_ONLY_INTERNAL_USERS` is true.
- **`events`** — `Event` (has slug, status, tags, playlists, presenters via `EventPresenter`) and `VideoAsset` (file, thumbnail, captions, duration, view_count). Tags/playlists are ordered by their most recent event time.

Auth defaults (`settings/base.py`): JWT (simplejwt) + session auth, and `IsAuthenticated` on every view. Login views opt out with `permission_classes = []`. Staff-only views add `IsStaffPermission` explicitly (e.g. `TagListView.get_permissions` allows GET for any user, POST for staff only).

### Event creation is a two-step flow
Staff first `POST /videoassets/` (multipart upload → `VideoAsset` with no event), then `POST /` with `video_asset_id` to create the `Event` and attach the asset (`EventCreateSerializer`). Events are always created `PUBLISHED`/`SESSION` with the requester as creator. Django admin is the other path to the same data, where `VideoAssetAdmin` can also enqueue `events.tasks.download_google_drive_video` from a Drive link, and `EventAdminForm` attaches an asset via a non-model `videoasset` field.

### Resumable uploads
Large videos go through `/api/v1/events/videoassets/` (JSON `POST` starts a session, `videoassets/<uuid>/` takes chunks; multipart `POST` is still the single-request upload). Logic is in `events/v1/uploads.py` (`UploadSession` model), finalization in the `events.tasks.finalize_upload_session` Celery task. The committed `offset` is the source of truth and only moves after the chunk is fsynced under a row lock. See `UPLOADS.md` before changing any of it; `cleanup_upload_sessions` runs hourly via `CELERY_BEAT_SCHEDULE`, so a `celery beat` process (the `celery-beat` compose service) must be running.

### Things that are easy to trip over
- **`VideoAsset.save()` runs ffmpeg synchronously** whenever `video_file` is set: it saves, probes duration, extracts a thumbnail at ~20% of the duration, then saves again with `update_fields`. ffmpeg errors are logged, not raised, leaving `duration == 0` (the upload serializer treats that as `FAILED`). Use `QuerySet.update()` when you only need to touch other columns (as `VideoAssetIncrementViewCountView` and `VideoAssetCreateSerializer` do). The `ffmpeg` binary must be installed.
- **Event slugs are set by a `post_save` signal** (`events/signals.py`), appending the id when the title already exists. `events/tests/conftest.py` disconnects it for every test (autouse), so factories set `slug` themselves.
- **Storages are module-level `FileSystemStorage` instances** built from `MEDIA_ROOT` at import time in `events/models.py` (`videos/`, `thumbnails/`, `captions/`). Tests that upload files must use the `media_storage` fixture, which monkeypatches the `video_file` and `thumbnail` field storage (not `captions_file`) to a tmp dir.
- **Tests run without migrations** (`settings/test.py` sets `MIGRATION_MODULES = DisableMigrations()`), and `events/tests/conftest.py` creates the `pg_trgm` extension. If you add a Postgres extension or a data migration, tests won't exercise it. Test DB credentials come from `DB_*` env vars, defaulting to `testuser`/`testpassword`@`localhost`.
- **Settings layering**: `settings/base.py` reads `.env` via `python-dotenv` and ends with `from .local import *` (silently ignored if missing). `base.py` hardcodes `DATABASES` with an empty user, so only `local.py` (which reads `DB_*`) gives a working dev database. `DEBUG = os.getenv("DJANGO_DEBUG", False)` is truthy for any non-empty string, including `"False"`. `settings/__init__.py` re-exports `base`, and `manage.py`/wsgi/asgi default to that package (`arbisoft_sessions_portal.settings`); `pytest.ini` points at `settings.test` and `celery.py` at `settings.base`. Celery broker defaults to `redis://redis:6379/0` (the docker-compose hostname); tests use `memory://`. Sentry is initialised by `arbisoft_sessions_portal/sentry.py` from the package `__init__`, not in settings; `settings/test.py` sets `SENTRY_DSN = None` so a DSN in `.env` never reports test errors.
- Models use `on_delete=DO_NOTHING` for `Event` FKs, and `EventAdmin` disables deletion.
- Event search (`EventFilter.filter_search`) is trigram similarity (threshold 0.3) OR `icontains` across title/description plus playlist/tag/presenter name matches, ordered by `-event_time`; list endpoint only returns events that have at least one video.

## Conventions

- Line length 120; isort sections are `FUTURE, STDLIB, THIRDPARTY, DJANGO, FIRSTPARTY, LOCALFOLDER` (Django imports are their own block between third-party and first-party). Migrations are excluded from lint.
- pylint runs with `pylint_django`; `max-args = 5`, `max-locals = 15`, `max-branches = 12`.
- Logger name is `asp_api` (writes `api.log` / `api_error.log` in the working directory).
- `DATABASE_DESIGN.md` has the ER diagram of the schema; update it in the same change as a model change.
