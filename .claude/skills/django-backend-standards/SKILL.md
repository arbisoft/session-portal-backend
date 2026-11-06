---
name: django-backend-standards
description: Django/DRF coding rules for the Sessions Portal backend — views, serializers, filters, models, settings, and project traps (ffmpeg on save, slug signal, storages). Used by backend-agent when building models, views, serializers, and APIs. For migration rules see django-migration-standards.
---

# Django Backend Standards

Rules for views, serializers, models and project traps (ffmpeg on save, slug signal, storages, `DO_NOTHING`, Google login gate) are in `.claude/rules/backend-django.md` and `CLAUDE.md`; this skill is the checklist.

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

## Settings

- `settings/base.py` reads `.env` via python-dotenv and ends with `from .local import *` (silently ignored if missing). `settings/local.py` is gitignored; `local.example.py` is the template.
- New configuration: read from the environment in `base.py` with a safe default, and add the key to `local.example.py` and the README setup notes so a fresh checkout boots.
- Never put secrets in `base.py`. `DJANGO_SECRET_KEY` and OAuth credentials come from the environment.
- `settings/test.py` is test-only (migrations disabled, `memory://` Celery broker, `DB_*` env vars). Don't import it from app code.

## Migrations

Follow `.claude/skills/django-migration-standards/SKILL.md`.
