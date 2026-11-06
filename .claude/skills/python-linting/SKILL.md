---
name: python-linting
description: Lint workflow (pylint, pycodestyle, isort) and test naming conventions for the Sessions Portal backend. Used by backend-agent and qa-agent after every Python file change; mirrors exactly what CI runs.
---

# Python Linting & Test Naming

Standards (limits, disables, imports, comments) live in `.claude/rules/backend-python.md`; this skill is the procedure.

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

Fix import order with `tox -e isort`. Zero findings from all three is the bar. `tox -e quality` is the full gate before a PR.

Dev dependencies are in `requirements/dev.txt` (it does not include `base.txt`; install both).

## Shortening test names

The 50-character limit is in `.claude/rules/testing.md`. When a descriptive name is too long, drop filler (`with`, `on`, `the`) and abbreviate (`ok`, `empty`):

`test_patch_with_null_comment_on_flagged_choice_returns_200` (58) → `test_patch_null_comment_flagged_choice_ok` (41)
