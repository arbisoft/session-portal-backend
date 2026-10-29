---
name: dead-code-sweep
description: Diff-scoped dead code detection and removal for the Sessions Portal backend — finds unused imports, unreachable code, commented-out blocks, and orphaned functions left behind on the current change, removes them, then re-lints. Trigger on "find dead code", "remove dead code", "clean up unused code", "dead code sweep", or before opening a PR when a branch may have orphaned code.
---

# Dead Code Sweep

Finds and removes dead code introduced or exposed by a **bounded diff** — never a whole-repo sweep. `.claude/rules/backend-python.md` already forbids dead and commented-out code; this skill is the procedure that hunts it.

## Modes

- **Standalone** (default) — run end to end: scope, detect, delete, re-lint, report.
- **Review-only** — `portal-code-review` dispatches this skill with the diff scope already resolved. Skip Scope Selection, run detection only (through the cascade check), do not delete, re-lint, or commit. Emit findings in `[SEVERITY] path:line — problem` / `Fix:` format and return.

## Scope Selection (Standalone)

Ask which diff to sweep unless the prompt already names it. Two options:

1. **Current diff** — uncommitted and staged changes
2. **Current branch** — every commit since the branch forked from `main`

```bash
git diff --name-only; git diff --cached --name-only     # option 1, union
git fetch origin main
git diff origin/main...HEAD --name-only                  # option 2
```

Option 2 is commits only; offer option 1 separately for uncommitted work on top. Only files in the resulting diff are deletion candidates. Restrict to `.py` files under `events/`, `users/`, `arbisoft_sessions_portal/`.

## What counts as dead

1. **Unused imports** — read from `pylint` (`unused-import`, `W0611`); don't hand-roll detection. An unused import often means its sole consumer function is now dead too; check that function against case 4 and remove it, not just the import line.
2. **Unreachable code** — statements after an unconditional `return`/`raise`/`continue`/`break` (pylint `W0101`).
3. **Commented-out code** — `#` lines containing code rather than prose.
4. **Orphaned functions / methods / classes** — touched in the diff and with zero callers anywhere in the repo. Confirm with a repo-wide grep of the symbol, not a diff-local check.
5. **Orphaned files** — a module whose symbols have no references and which is not wired into `urls.py`, `admin.py`, `apps.py`, `celery.py`, or an `__init__.py`.
6. **Cascading dead code** — deleting a function's only caller can orphan the function, its imports, and its sole helper. Sweep to a fixed point: after each deletion recheck the file and anything whose only reference is gone.

## Never auto-delete — flag instead

- Anything under `**/migrations/`.
- Anything referenced only by string or dynamic lookup: `apps.get_model()`, `getattr`, `reverse("name")`, URL names, Celery task names (`events.tasks.download_google_drive_video` is enqueued from admin by name), signal receivers connected via `AppConfig.ready()`, `settings` dotted paths, `INSTALLED_APPS`.
- Django admin registrations and actions, `ModelForm` classes used only by admin, management commands (`events/management/commands/`), which are invoked by name.
- drf-spectacular schema hooks and serializers referenced only from `extend_schema`.
- Model fields — dropping one needs a migration; hand it to `backend-agent`.
- Factories and fixtures used only by string or trait.
- Anything where diff and repo-wide grep disagree — ambiguous, not dead.

When in doubt, report it rather than deleting it.

## Procedure

Steps 1–4 run in both modes; 5–7 are Standalone only.

1. Compute the file list for the chosen mode (or use the caller's list in review-only mode).
2. Re-check each candidate against the current working tree. If it no longer exists, drop it silently.
3. Scan the scoped files for each category above; verify orphan status with a repo-wide grep.
4. Apply the cascade check until a full pass finds nothing new. The cascade may reach files outside the original diff; exclude anything on the never-delete list.
5. **(Standalone)** Make the deletions, minimal and in the same working tree. Hand non-trivial removals to `backend-agent`.
6. **(Standalone)** Re-run `pylint`, `pycodestyle`, `isort --check-only` on every touched file, and the tests that cover them. If a deletion introduces a new error, fix it in the same pass or revert that deletion.
7. **(Standalone)** Report:
   - **Scope** — mode and base used
   - **Removed** — `file:line`, what it was, why it was dead
   - **Flagged, not removed** — `file:line` and why it was ambiguous

Deletions stay as local uncommitted changes for the user to review; this skill does not commit or push.
