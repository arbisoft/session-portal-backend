---
paths:
  - "**/*.py"
---

# Backend — Python Standards

CI runs `tox -e quality`: `pylint events users`, `pycodestyle events users`, `isort --check-only`. Code must pass all three. Line length is 120.

## Naming

- `snake_case` for variables, functions, model fields; `PascalCase` for classes.
- Descriptive, intention-revealing names — avoid single-letter or unexplained abbreviations.

## Pylint-Friendly Code

- No unused imports or variables.
- No dead code or commented-out blocks.
- No duplicated branches.
- Prefer small functions with early returns over deep nesting.
- Respect `pylintrc` (the source of truth): `max-args = 5`, `max-locals = 15`, `max-branches = 12`, `max-returns = 6`, `max-statements = 50`, `max-attributes = 7`, `min-public-methods = 2`.
- `min-similarity-lines = 4`: duplicated blocks across files trip `duplicate-code`. Extract a helper; tests that legitimately repeat setup have precedent for a file-level disable.
- Import order is isort with a separate Django block: `FUTURE, STDLIB, THIRDPARTY, DJANGO, FIRSTPARTY, LOCALFOLDER`. Fix with `tox -e isort`.
- Migrations are excluded from lint.

## Comments and Lint Disables

- Do not write inline `#` comments that narrate code. If a function needs explanation, use a short docstring.
- Do not reference the ticket, PR, or fix in code. That context belongs in the PR description.
- Fix a lint finding by changing the code. A `# pylint: disable=<rule>` is acceptable only for a specific, justified case that already has precedent in the repo: `unused-argument` on signal handlers and pytest fixtures, `protected-access` on `_meta` in tests, `import-outside-toplevel` for the signal import in `AppConfig.ready()`. One rule per disable, never blanket or `disable=all`.
- No `# noqa` for line length — wrap the line.

## Imports

- Keep imports at the top of the module. The one existing exception is the signal import inside `EventsConfig.ready()`.
- If a top-level import causes a circular dependency, restructure (move the shared symbol) before reaching for a local import.

## Error Handling

- No `print()` — use `logging`.
- No bare `except Exception: pass` — handle, log with context, or re-raise.
- Avoid broad `except Exception` unless it logs and re-raises or returns a deliberate fallback. ffmpeg failures in `VideoAsset.save()` are logged on purpose; keep that behavior explicit.
- Error messages to clients must not leak internal IDs, stack traces, or file-system paths.

## Logging

- Logger name is `asp_api` — the only logger configured in `settings/base.py` `LOGGING` (console, `api.log`, `api_error.log`, mail_admins).
- Use `logger = logging.getLogger("asp_api")` in new modules. Loggers created with `getLogger(__name__)` have no handler configured, so INFO/WARNING records from them are dropped.
- ERROR and above: `logger.exception(...)` inside `except` blocks so the traceback is kept.

## Type Hints & Docstrings

- Type hints on new functions.
- Docstrings on non-trivial models, helpers, and any function whose name alone does not carry the contract. Keep them accurate when behavior changes.

## DRY

- Check `<app>/v1/utils.py`, model methods, and `users/permissions.py` before writing a new helper.
- No copy-paste between endpoints — centralize repeatable logic.
