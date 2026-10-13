---
name: python-linting
description: Lint workflow (pylint, pycodestyle, isort) and test naming conventions for the Sessions Portal backend. Used by backend-agent and qa-agent after every Python file change; mirrors exactly what CI runs.
---

# Python Linting & Test Naming

## What CI runs

`tox -e quality` over `events users`:

```bash
pylint events users
pycodestyle events users
isort --skip migrations --check-only --diff events users
```

Config: `pylintrc` (plugin `pylint_django`, migrations and `management` ignored, max line 120), `[pycodestyle]` and `[isort]` in `tox.ini`. There is no flake8 in this repo.

## After every Python change

Run on each changed file before reporting done:

```bash
pylint <file1.py> <file2.py>
pycodestyle <file1.py> <file2.py>
isort --skip migrations --check-only --diff <file1.py> <file2.py>
```

Fix with `tox -e isort` for import order. Zero findings from all three is the bar. `tox -e quality` is the full gate before a PR.

Dev dependencies are in `requirements/dev.txt` (it does not include `base.txt`; install both).

## Limits that bite (pylintrc)

- `max-args = 5`, `max-locals = 15`, `max-branches = 12`, `max-returns = 6`, `max-statements = 50`, `max-attributes = 7`, `min-public-methods = 2`
- `min-similarity-lines = 4` — duplicated blocks across files trip `duplicate-code`; extract a helper (tests that legitimately repeat setup have precedent for a file-level disable).
- isort sections: `FUTURE, STDLIB, THIRDPARTY, DJANGO, FIRSTPARTY, LOCALFOLDER`; Django imports are their own block.

## Comments and disables

- Don't write inline comments that narrate code; use a short docstring for the non-obvious.
- Fix a finding by changing code. Existing precedent for disables is narrow: `unused-argument` on signal handlers and pytest fixtures, `protected-access` on `_meta` in tests, `import-outside-toplevel` for the signal import in `AppConfig.ready()`. One rule per disable; never `disable=all`.
- No `# noqa`. Wrap long lines.

## Imports

- Keep imports at the top of the module. For a circular import, move the shared symbol to a third module before considering a local import, and tell the user if you can't avoid it.

## Test naming

- Test method names are snake_case and at most 50 characters. This is a house convention; pylint's default naming has no upper bound and `pylintrc` sets no `method-rgx`, so the linter will not flag a longer name.
- If a descriptive name is too long: drop filler (`with`, `on`, `the`), and abbreviate (`ok`, `empty`).
  `test_patch_with_null_comment_on_flagged_choice_returns_200` (58) → `test_patch_null_comment_flagged_choice_ok` (41)
