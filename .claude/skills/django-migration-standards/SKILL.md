---
name: django-migration-standards
description: Migration practices for the Sessions Portal backend — one migration per change, schema/data separation, reversibility, backwards compatibility, and the mandatory verification protocol (the test suite does not run migrations). Read by backend-agent whenever models or migrations change and by backend-reviewer-agent during review.
---

# Django Migration Standards

Applies to `events/migrations/` and `users/migrations/`. Migrations are excluded from lint.

## Why verification is mandatory

`settings/test.py` sets `MIGRATION_MODULES = DisableMigrations()`: the test database is built straight from `models.py`. A green `pytest` run proves nothing about a migration file — not that it applies, not that it reverses. CI runs only `tox -e quality` and `pytest`; nothing in CI runs `makemigrations --check`. The protocol below is the only check.

## One migration per change

- A model change ships with its migration in the same PR.
- Within one PR, an app should gain **one** new migration file. If you generated several while iterating, delete them and regenerate one: the not-yet-merged migrations are yours to rewrite.
- Exceptions (keep split): schema and data changes (see below); a file already merged to `main`/`stage` (never rewrite shared history); migrations in different apps.
- Never use `squashmigrations` for this. It is for already-shared history and has its own review.
- Name the file descriptively (`makemigrations <app> -n add_videoasset_view_count`) rather than keeping an auto-generated `alter_..._and_more` name.

## Schema vs data

- Never mix a schema change and `RunPython` in one file. Schema first, data second, two files.
- Data backfills are data migrations (see `0010_populate_event_slugs.py`), not ad-hoc scripts or management commands.

## Data migration rules

- Resolve models with `apps.get_model('<app>', '<Model>')` — never import from `<app>.models`. The historical model has no custom methods, no signals (the slug signal will not fire), and no custom `save()` (`VideoAsset.save()` and its ffmpeg call do not run).
- The repo has no custom managers on historical models, so `Model.objects` is fine. If a custom manager is ever added, use `Model._base_manager` in migrations.
- Use `save(update_fields=[...])`, `update()`, or `bulk_update()`; iterate large tables with `.iterator()` rather than loading everything.
- Prefer ORM over raw SQL. If raw SQL is genuinely needed, say why in the docstring.
- Give every file containing `RunPython` a short module docstring explaining what it does.
- Row-level work that can fail on bad data: catch the specific exception, count successes/skips/errors, and log a summary with `logging.getLogger("asp_api")`.

## Reversibility

- Every migration should be reversible. Provide a real `reverse_code` when a meaningful inverse exists.
- When one-way is genuinely correct, use `migrations.RunPython.noop` and state why in the docstring (as `0010` does with `reverse_code=migrations.RunPython.noop`).
- A reverse that silently discards state a real reverse would restore is a bug — write the reverse.

## Backwards compatibility (PR template requirement)

The previous app version keeps running during deploy, so a migration must work with both code versions:

- Adding a column: nullable or with a default.
- NOT NULL on a populated table: add nullable → backfill (data migration) → set NOT NULL in a later PR.
- Renames and drops: deploy the code that stops using the field first; drop in a later PR. Do not rename and use in one PR.
- Index on a large table: use `AddIndexConcurrently` in a non-atomic migration (`atomic = False`).
- Postgres extensions go through `CreateExtension` (see `0011_add_pg_trgm_extension.py`). The test DB does not run it; `events/tests/conftest.py` creates `pg_trgm` itself, so a new extension also needs a conftest line.

## Mandatory verification protocol

Run against the **local dev database** (the Postgres that `manage.py migrate` targets), not the test DB:

```bash
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py migrate <app> <migration_before_this_change>
python manage.py migrate <app> <new_migration>                    # forward
python manage.py migrate <app> <migration_before_this_change>     # reverse
python manage.py migrate <app>                                    # leave DB at head
```

Report the output. For a data migration, also confirm the forward run changed the rows you expect and that the reverse did what the docstring says.

## Detecting this change's migrations

```bash
git fetch origin main
git diff --name-status --diff-filter=A origin/main...HEAD -- '*/migrations/*.py'
git status --porcelain -- '*/migrations/*.py'     # uncommitted ones
```

Group by app. Two or more new files for one app (excluding the schema/data split) → propose a merge to the user and wait for confirmation before deleting or renumbering anything. After merging, fix any `dependencies` that pointed at a deleted file and rerun the protocol.
