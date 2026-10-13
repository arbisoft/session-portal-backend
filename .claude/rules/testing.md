# Testing Rules

## Running

```bash
pytest --cov --cov-report=term                              # CI command
pytest events/tests/test_apis.py::TestClassName::test_name  # single test
```

- Runner is `pytest` + `pytest-django` (`arbisoft_sessions_portal.settings.test`); a reachable Postgres is required.
- Coverage gate is `fail_under = 80` (`.coveragerc`); migrations and tests are omitted. New code must not lower it.

## Coverage Expectations

- All new business logic includes unit tests.
- All new API endpoints include integration tests with `APIClient`.
- Cover edge cases and error paths — permission denial (anonymous, non-staff), validation errors, missing objects — not just the happy path.
- Assert status codes, response shape, and side effects (rows created, `view_count` incremented, queued task).

## Organization

- Tests live in `<app>/tests/`: `test_apis.py`, `test_staff_apis.py`, `test_filters.py`, `test_forms.py`, `test_tasks.py`. Extend the matching file before creating a new one.
- Test method names are snake_case and at most 50 characters. This is a house convention: pylint's default naming (3.3.3) has no upper bound and `pylintrc` sets no `method-rgx`, so CI does not catch a longer name.
- Descriptive names that explain the scenario.

## Fixtures and Data

- Use the `factory_boy` factories in `events/factories.py` and `users/factories.py`, not raw `Model.objects.create` or JSON fixtures.
- Existing fixtures in `events/tests/conftest.py`: `staff_client`, `user_client`, `media_storage`. Reuse them.
- Tests that upload files must use `media_storage` so files land in a tmp dir, not `MEDIA_ROOT`.
- The `Event` slug signal is disconnected for every test (autouse), so factories must set `slug` explicitly.
- Do not call real Google APIs or Celery brokers. Mock the HTTP layer (`responses` is installed) and use the `memory://` broker from test settings.
- ffmpeg-dependent paths: patch the probe/thumbnail step unless the test is specifically about it.

## Migrations

- The test DB is built from `models.py` with migrations disabled, so tests prove nothing about migration files. Verification is governed by the `django-migration-standards` skill.
- Anything that depends on a Postgres extension or a data migration needs setup in `conftest.py` to be exercised.
