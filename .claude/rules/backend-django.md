# Backend — Django Rules

## Layout

- Each app exposes a versioned API under `<app>/v1/` (`serializers.py`, `views.py`, `urls.py`; `events` also has `filters.py`, `pagination.py`, `utils.py`).
- A new API version is a sibling package (`v2/`), never an edit that changes the contract of `v1`.
- Shared permission classes live in `users/permissions.py` (`IsStaffPermission`), including for `events` endpoints.

## View Discipline

- Views handle request flow: parse input, call helpers, return response.
- Keep a view scoped to its endpoint. Do not pack validation + persistence + formatting into one method.
- Logic shared across endpoints goes to `<app>/v1/utils.py`, model methods, or queryset helpers.
- Do **not** create `services.py` by default. Avoid thin pass-through wrappers. `arbisoft_sessions_portal/services/` is reserved for external-system clients (Google).
- Use `get_object_or_404()` — no manual `try: .get() except DoesNotExist`.
- Use generic DRF views (`ListAPIView`, `CreateAPIView`, ...) for CRUD, `APIView` for one-off endpoints.
- Query-param filtering belongs in a `django_filters` `FilterSet` (`events/v1/filters.py`). When a view needs a bare param, validate it through a serializer instead of `request.query_params.get()` + manual casting.
- Every view is covered by the global `IsAuthenticated` default. Opt out (`permission_classes = []`) only for login endpoints. Staff-only endpoints add `IsStaffPermission` explicitly.

## Query Optimization

- `select_related()` for ForeignKey / OneToOne, `prefetch_related()` for M2M / reverse FK. Check serializers and properties, not just the view.
- No N+1 — `SerializerMethodField`s and model properties must use prefetched data (`.all()`, not `.filter()`). See the `django-query-optimisation` skill.
- Event list/detail endpoints traverse `creator`, `tags`, `playlists`, `presenters`, and the reverse `videos` relation; any new field on them needs matching `select_related`/`prefetch_related`. `.first()` and `.filter()` on a related manager bypass the prefetch cache.
- `bulk_create()` / `bulk_update()` for batches — never loop-save.
- `.only()` / `.defer()` or `values()` on hot paths when full rows are not needed (see `VideoAssetIncrementViewCountView`).
- `QuerySet.update()` when touching columns on a `VideoAsset` without needing ffmpeg: `VideoAsset.save()` runs ffmpeg whenever `video_file` is set.

## Serializers

- Serializers handle validation and representation only — no side effects (emails, writes to other models).
- Separate serializers for list / detail / create when field sets differ (`EventCreateSerializer`, `VideoAssetCreateSerializer`).
- Use `read_only_fields`. Never expose passwords, tokens, or internal-only IDs.
- A create/update serializer that writes a field gated by a business rule must enforce the rule in `validate()` / `validate_<field>()`. Permission classes only say whether the caller may hit the endpoint.
- Do not duplicate validation that belongs in model `clean()` or field validators (e.g. the `VideoAsset.video_file` extension validator).

## Models

- Every model needs `__str__()`.
- Prefer database-level constraints (`unique_together`, `CheckConstraint`) over app-only validation.
- `db_index=True` on fields used in frequent filters and lookups.
- Define `Meta.ordering` only when necessary.
- `Event` foreign keys use `on_delete=DO_NOTHING` and `EventAdmin` disables deletion — keep new relations consistent with that choice and say why if they differ.
- Event slugs are assigned by the `post_save` signal in `events/signals.py`. Do not set them elsewhere.
- File fields use the module-level storages in `events/models.py`; don't instantiate storages in views or serializers.

## Migrations

- Any model, field, constraint, or relation change ships with its migration in the same PR.
- Tests run with migrations disabled (`DisableMigrations`), so a green suite does not prove a migration works. Follow the `django-migration-standards` skill.
- Data backfills use a data migration, not an ad-hoc script. Keep schema and data in separate files.
- Watch for: NOT NULL without default on populated tables, irreversible `RunPython`, rename-and-use in one PR, new Postgres extensions (the test DB creates `pg_trgm` in `conftest.py`, not through migrations).
- Migrations must stay backwards-compatible with the code currently deployed (PR template requirement).

## Celery Tasks

- Celery is used for Google Drive video imports and for resumable-upload finalization and cleanup (`events/tasks.py`). Tasks must be idempotent.
- Use `logging`, not `print()`.
- Pass IDs to tasks, not model instances.
