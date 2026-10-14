# Backend Review Checklist

Authoritative: `.claude/rules/backend-django.md`, `solid.md`, `security.md`. This is a checklist, not a rulebook — open the rule file when you need depth.

## Universal (every backend diff)

- [ ] No hardcoded secrets, API keys, tokens, DB URLs
- [ ] No `print()` — `logging.getLogger("asp_api")`
- [ ] No commented-out code; no narrating inline comments
- [ ] No bare `except Exception: pass`
- [ ] No magic numbers — module-level constants (e.g. the 20% thumbnail offset, the 0.3 trigram threshold)
- [ ] Error messages don't leak internal IDs, stack traces, file paths, or ffmpeg output

## Views

- [ ] View does request flow only; shared logic in `utils.py` / model methods
- [ ] `get_object_or_404`, not manual `try/except DoesNotExist`
- [ ] Query params handled by a `FilterSet` or serializer, not manual casting
- [ ] `permission_classes = []` only on login views; staff-only endpoints use `IsStaffPermission`
- [ ] New route is registered in `<app>/v1/urls.py` and documented through drf-spectacular where sibling views are

## Serializers

- [ ] Validation and representation only — no side effects
- [ ] Separate list / detail / create serializers when field sets differ
- [ ] `read_only_fields` set; no password/token/internal fields exposed
- [ ] Business-rule fields enforced in `validate()` / `validate_<field>()`

## ORM performance

- [ ] `select_related` for FKs walked in loops or serializers (`creator`; `event__creator` from a `VideoAsset`)
- [ ] `prefetch_related` for M2M/reverse FK (`tags`, `playlists`, `presenters`, `videos`)
- [ ] No `SerializerMethodField` / property hitting the DB per row; no `.filter()` on a prefetched manager
- [ ] `.only()` / `.defer()` / `values()` on hot paths where full rows aren't needed
- [ ] `bulk_create` / `bulk_update` over loop-save
- [ ] `.exists()` / `.count()` instead of `len(qs)` / `if qs`
- [ ] Filterable fields indexed (`db_index=True`)
- [ ] Details and fixes: `.claude/skills/django-query-optimisation/SKILL.md`. SUGGESTION; BLOCKER on a list endpoint.

## Project-specific traps

- [ ] `VideoAsset.save()` not used where `QuerySet.update()` suffices (view-count, duration, status writes)
- [ ] ffmpeg failure path still handled (`duration == 0` → FAILED); no new ffmpeg call on a request path without a reason
- [ ] Event slug set only by the `post_save` signal
- [ ] New file fields use the module-level storages from `events/models.py`
- [ ] Search changes keep `EventFilter.filter_search` semantics (trigram ≥ 0.3 OR `icontains`, ordered by `-event_time`, only events with a video)
- [ ] Tag/playlist ordering by most recent event time preserved
- [ ] Google login still enforces `hd` allow-list while `ALLOW_ONLY_INTERNAL_USERS` is true

## SOLID (apply with judgement)

- [ ] **S** — a view/class doing more than one of {validate, persist, notify, format} → SUGGESTION split
- [ ] **O** — growing if/elif chain on a type → strategy map
- [ ] **L** — `save()` / `clean()` / `delete()` override without `super()`; subclass changing the parent contract
- [ ] **I** — list endpoint returning the detail payload
- [ ] **D** — raw `requests` calls or complex ORM chains in a view instead of `services/` or a helper

Do not flag SOLID on a 10-line utility, a throwaway test helper, or code the diff only touches tangentially.

## Models / Migrations

- [ ] `__str__` on new models
- [ ] `Meta.ordering` only when a stable default sort is needed
- [ ] Model change has its migration in the same PR
- [ ] Backwards-compatible with the deployed code (no rename-and-use in one PR)
- [ ] No NOT NULL without default on a populated table
- [ ] `RunPython` has a real `reverse_code`, or `migrations.RunPython.noop` with the reason in the docstring
- [ ] Schema and data changes in separate files
- [ ] Large-table index uses `AddIndexConcurrently` (non-atomic migration) where relevant
- [ ] 2+ new migrations for one app in the diff → should be one file unless split for a documented reason

## Celery

- [ ] Task is idempotent, takes IDs not instances, logs failures with context
- [ ] Task failure leaves the `VideoAsset` in a visible failed state rather than silently pending

## Security

- [ ] No raw SQL with string interpolation; no user input into `.extra()` / `.raw()`
- [ ] Upload fields validated (extension, and size/type where relevant)
- [ ] User-supplied URLs (Google Drive links) restricted to the expected host
- [ ] No ad-hoc `is_staff` checks in view bodies
- [ ] Responses expose no sensitive user fields

## Tests

- [ ] New logic has unit tests; new endpoint has `APIClient` tests incl. anonymous and non-staff cases
- [ ] Edge cases and error paths covered
- [ ] Factories used; `slug` set on events; `media_storage` used for uploads
- [ ] No real network or ffmpeg dependency unless the test is about it
- [ ] Test names ≤ 50 chars
