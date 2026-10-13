---
name: documentation-generator
description: Use when a change to the Sessions Portal backend (Django 4.2 + DRF, apps `events` and `users`) makes README.md, CLAUDE.md, DATABASE_DESIGN.md, or `.claude/rules/` inaccurate, or when auditing them for gaps - setup, environment variables, commands, architecture, data model, business rules, Celery/ffmpeg/Docker requirements, and contribution workflow. Derives every claim from the code, tooling config, and generated OpenAPI schema, then automatically hands off to documentation-reviewer for a wording/accuracy pass before finishing. Self-heals its own file map when the repo's documentation layout changes.
---

# Documentation Generator

## Summary

Audit the documentation of this repo against the code and repair what is missing, stale, or contradictory. Then hand the touched files to `documentation-reviewer` for a wording and accuracy pass.

Core principle: **documentation must reflect the code and tooling as they are, not as someone remembers them.** A command, env var, endpoint, or field name in a doc is a claim; verify it against the file that defines it.

Invoking this skill runs the **whole pipeline**: inventory → audit → generate/repair → validate → hand off to `documentation-reviewer` (Step 10). Step 10 is part of "done"; do not stop after Step 9.

## Documentation map

This repo has no `docs/` or `plans/` directory and no `CHANGELOG.md` / `CONTRIBUTING.md`. Each fact has one home; other files link to it instead of copying it.

| File | Audience | Holds |
| --- | --- | --- |
| `README.md` | New developer | Setup from scratch (venv and Docker paths), env vars, how to run the server, tests, and lint |
| `CLAUDE.md` | Claude Code sessions | Commands, architecture, "easy to trip over" traps, conventions. Always loaded, so it is budget-constrained: follow the `claude-md-writing` skill before editing |
| `DATABASE_DESIGN.md` | Developer, DBA | Mermaid ER diagram of the intended schema (known to predate some fields; see reviewer's Known drift) |
| `.claude/rules/*.md` | Contributors and agents | Coding standards: Django, Python/lint, SOLID, security, testing, branching/PR. Indexed by `.claude/rules/README.md` |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR author | Description, Taiga ticket link, review count, migration compatibility |
| Generated OpenAPI schema | API consumers | `/api/schema/`, `/api/docs/` (Swagger), `/api/redoc/` via drf-spectacular. There is **no hand-written API reference** |

If the README outgrows one page, add a `docs/` folder with topic-per-file docs and link them from the README. Do this only when a topic has real content; never create empty or placeholder files.

## Applies When

- Generating or refreshing documentation for the repo
- A code change makes a doc claim wrong: a new/renamed env var, command, endpoint, model field, Celery task, management command, or setting
- A new system requirement appears (a binary like ffmpeg, a service like Redis, a Postgres extension)
- Onboarding material is missing or a new developer could not get running from the README alone
- The rules in `.claude/rules/` no longer match `tox.ini`, `pylintrc`, `.coveragerc`, or CI

Do not use when:

- Only an inline code comment or docstring is needed
- The request is a code review (use `portal-code-review`)
- The request is to write or trim `CLAUDE.md` rules on their own (use `claude-md-writing`)

## Must

- Read the source of truth for a claim before writing it (see the table in Step 9)
- Review existing docs before restructuring; preserve useful content and the file's established structure
- Document exact commands, not descriptions of commands ("run `tox -e quality`", not "run the linter")
- Document every external requirement: PostgreSQL (with `pg_trgm`), ffmpeg binary, Redis and a Celery worker for Drive imports, Docker/compose where relevant
- Mark unknowns explicitly rather than inventing detail
- Keep README and `CLAUDE.md` consistent where both state the same fact (commands, Python/Postgres versions, env vars)
- End every run with the Step 10 handoff

## Must Not

- Invent endpoints, env vars, scripts, settings, or workflows that are not in the code
- Open, print, or copy values from `.env` or `arbisoft_sessions_portal/settings/local.py`; both are gitignored and may hold real secrets. Document variable **names** from `README.md`, `settings/base.py`, `settings/test.py`, and `docker-compose.yml`
- Hand-write an endpoint reference or duplicate the generated OpenAPI schema into Markdown
- Paste long procedures into `CLAUDE.md`; link to the README or a rules file instead
- Create `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/`, or `plans/` without the user asking (`rules/branching.md` and the PR template already are the contribution docs)
- "Fix" a doc to match behavior that looks like a code bug; report it as a finding (for example, `DEBUG = os.getenv("DJANGO_DEBUG", False)` treats any non-empty string, including `"False"`, as truthy)
- Remove accurate content, or restyle a section that is already correct
- Skip the Step 10 handoff because the change "looks small"

## Required Documentation Coverage

| Area | Required content | Lives in |
| --- | --- | --- |
| Project overview | Purpose, main features, tech stack | `README.md`, `CLAUDE.md` → Project |
| Prerequisites | Python 3.12, PostgreSQL 16, ffmpeg, Redis (Drive imports only), Docker (optional) | `README.md` |
| Setup | Clone, venv, `pip install -r requirements/base.txt` (+ `dev.txt` for tests/lint), `.env`, `local.py`, database, `migrate`, `runserver` | `README.md` |
| Environment variables | `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_PORT` (compose only), with what reads each | `README.md` |
| Usage | Run server, Celery worker, management commands, Django admin | `README.md`, `CLAUDE.md` → Commands |
| Architecture | Two apps, `v1/` API packages, services dir, settings layering, auth model | `CLAUDE.md` → Architecture |
| Data model | Models, relations, `on_delete` choices, constraints | `DATABASE_DESIGN.md` + `events/models.py` |
| Business rules | Two-step event creation, search behavior, ordering, staff gating, internal-domain login | `CLAUDE.md` → Architecture / traps |
| API | Paths, auth, request/response shapes | Generated OpenAPI; docs only point to it |
| Background jobs | `events.tasks.download_google_drive_video`, broker/result backend, idempotency | `CLAUDE.md`, `.claude/rules/backend-django.md` |
| Testing | `pytest` commands, Postgres requirement, fixtures, coverage gate | `README.md`, `.claude/rules/testing.md` |
| Code standards | Lint gate, naming, imports, error handling | `.claude/rules/backend-python.md`, `backend-django.md`, `solid.md` |
| Security | Secrets, validation, permissions, high-scrutiny surfaces | `.claude/rules/security.md` |
| Development workflow | Branching, commits, PR checklist | `.claude/rules/branching.md`, PR template |
| Deployment | CI image build on GitHub release, Docker targets | `README.md` (what exists), not an ops runbook |
| Troubleshooting | Only real, previously hit failures: symptom → cause → fix | `README.md` section, when one exists |

**Self-heal check:** this table is a claim about what this project needs documented. If a run finds a category that fits no row (a new integration, a new deploy target, a new background job type), add a row in the same pass.

## Workflow Steps

### 1. Inventory the Codebase

Review, in this order:

- Root: `README.md`, `CLAUDE.md`, `DATABASE_DESIGN.md`, `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `tox.ini`, `pylintrc`, `pytest.ini`, `.coveragerc`
- `requirements/base.txt`, `requirements/dev.txt`
- `.github/workflows/ci.yml`, `.github/workflows/build-and-push-container-image.yml`, `.github/PULL_REQUEST_TEMPLATE.md`
- `arbisoft_sessions_portal/` (settings layering, `urls.py`, `celery.py`, `services/`)
- `events/` and `users/` (models, `v1/`, admin, forms, signals, tasks, management commands, tests, factories)
- `.claude/rules/`, `.claude/skills/`, `.claude/agents/` (read to know what is already documented there)

Build a mental map of what the project does before editing any doc. `git status` and `git log -5` show what changed recently and which docs may now be stale.

### 2. Audit Existing Documentation

For each doc, check: accurate, complete, current, not duplicated, not contradictory, and no missing workflow. Preserve useful content; correct stale or misleading statements.

### 3. Analyze Business Logic

For each feature or module that docs describe or should describe, capture what it is, who triggers it, where it lives, and its edge cases. Source places in this repo:

- **Event creation**: `POST videoassets/` then `POST /` with `video_asset_id` (`events/v1/serializers.py`, `events/v1/views.py`); admin path via `events/forms.py` and `events/admin.py`
- **Video processing**: `VideoAsset.save()` in `events/models.py` (ffmpeg probe and thumbnail, failure leaves `duration == 0`)
- **Drive import**: `events/tasks.py`, queued from `VideoAssetAdmin`
- **Slugs**: `events/signals.py`
- **Search and listing**: `events/v1/filters.py`, `events/v1/utils.py` (`get_similar_events`), `events/v1/pagination.py`
- **Auth**: `users/v1/views.py` (Google token and email/password login, user search), `users/permissions.py`, `arbisoft_sessions_portal/services/google/`
- **Operational commands**: `events/management/commands/` (`check_videoasset_status`, `prepopulate_events`)

If a rule spans several modules, document the end-to-end flow once, in the file that owns it.

### 4. Verify the API Documentation Surface

The API reference is generated, so the job is to make sure the *generator input* is right and that prose docs do not contradict it.

1. List the real routes from `arbisoft_sessions_portal/urls.py`, `events/v1/urls.py`, `users/v1/urls.py`. Note the inconsistent trailing slashes (`login`, `login/email` have none; the rest do).
2. Check that any doc naming an endpoint uses the exact path, method, auth requirement (`IsAuthenticated` default; `IsStaffPermission` on staff-only views; `permission_classes = []` on login), and status codes.
3. For views where DRF's inference is wrong (custom `APIView`, non-default response), confirm an `extend_schema` annotation exists, as in `events/v1/views.py` and `users/v1/views.py`. Add or fix annotations only when asked; report the gap otherwise.
4. To inspect the schema locally (needs the dev environment installed): `python manage.py spectacular --file schema.yml`, then delete the file; it is not committed.

### 5. Update README

The README is the entry point for a new developer. Keep its existing order (env vars → `local.py` → Option 1 venv → Option 2 Docker) and add what is missing rather than reorganizing.

Check that it covers:

- Project name, one-sentence purpose, tech stack
- Prerequisites, including **ffmpeg** (required by `VideoAsset.save()`) and **Redis + Celery worker** (Drive imports only)
- Installing `requirements/base.txt` and, for tests/lint, `requirements/dev.txt` (it does **not** include base)
- Env vars and where each is read
- Running the server, a Celery worker, tests (`pytest --cov --cov-report=term`), lint (`tox -e quality`, `tox -e isort`)
- The Docker path, with the correct filename `docker-compose.yml` and the `--profile dev` lint/test services
- Links to `/api/docs/`, `/api/redoc/`, and `.claude/rules/` or `CLAUDE.md` where deeper detail lives

### 6. Place New Documentation

Use the Documentation map above. Decision rule:

1. Is it a rule for how to write code? → `.claude/rules/<topic>.md` and an index row in `.claude/rules/README.md`.
2. Is it something an agent will trip over without being told? → `CLAUDE.md`, one or two lines, via `claude-md-writing`.
3. Is it something a human needs to get running or understand the system? → `README.md`.
4. Is it the shape of the data? → `DATABASE_DESIGN.md`.
5. Is it an endpoint contract? → serializer/view annotations, not Markdown.

**Self-heal check:** if the repo has since adopted a `docs/` folder, a `CHANGELOG.md`, or `CONTRIBUTING.md`, update the Documentation map in this file in the same pass.

### 7. New Developer Onboarding

Confirm the README alone is enough for someone to: install prerequisites, create `.env` and `local.py`, create the database, migrate, start the server, run the tests, run lint, and find the API docs. Key files to point them at: `events/models.py`, `events/v1/views.py`, `users/v1/views.py`, `users/permissions.py`, `events/tests/conftest.py`.

### 8. Contribution Guidelines

Contribution guidance already lives in `.claude/rules/branching.md` and `.github/PULL_REQUEST_TEMPLATE.md`. Do not duplicate it into a new file. Check that it matches reality:

- Branch naming and the `main`/`stage` relationship (`git branch -a`)
- Conventional commit scopes against `git log`
- CI behavior against `.github/workflows/ci.yml` (what it triggers on, what it runs)
- Release/deploy behavior against `build-and-push-container-image.yml` (triggered by a published GitHub release or manual dispatch)

### 9. Validate Documentation Against Code

Before finishing, verify each claim against its source:

| Claim | Source of truth |
| --- | --- |
| Python/Postgres versions | `Dockerfile`, `ci.yml`, `docker-compose.yml`, `README.md` |
| Install commands, dependency list | `requirements/base.txt`, `requirements/dev.txt` |
| Lint/test commands and env names | `tox.ini` (`quality`, `isort`, `isort-check`), `pytest.ini`, `.github/workflows/ci.yml` |
| Lint limits (line length 120, `max-args`, etc.) | `pylintrc`, `tox.ini` |
| Coverage gate | `.coveragerc` (`fail_under`) |
| Env vars | `settings/base.py`, `settings/test.py`, `settings/local.example.py`, `docker-compose.yml` |
| Settings values (CORS origin, JWT lifetimes, `ALLOW_ONLY_INTERNAL_USERS`, Celery broker) | `settings/base.py`, `settings/test.py` |
| Docker services and profiles | `docker-compose.yml`, `Dockerfile` targets |
| Endpoints | the three `urls.py` files, then the views |
| Model fields and constraints | `events/models.py` and `events/migrations/` |
| Management commands | `events/management/commands/` |
| Logger name and log files | `LOGGING` in `settings/base.py` |

Also:

- Verify every referenced file path exists and every Markdown link resolves
- `grep` README, `CLAUDE.md`, `DATABASE_DESIGN.md`, and `.claude/` for files or names the change deleted or renamed (`git status` shows `D`/`R`)
- Confirm `.claude/rules/README.md` lists every file in `.claude/rules/`
- Remove outdated or speculative claims

**Self-learning check (every run):** if this run found a structure not reflected here (a new doc file, a new source of truth, a new background job), fold it into the relevant section of this file in the same pass. Scope the edit to what you observed.

### 10. Hand Off to documentation-reviewer (mandatory)

Call the Skill tool with `skill: documentation-reviewer` and `args` naming the exact files this run created or touched, for example:

`args: "chained scope: README.md, CLAUDE.md — skip Phase 1 discovery, run Phase 3 (including the wording/grammar/clarity pass) through Phase 7 against only these files"`

That is the reviewer's "chained invocation" scope. Apply the fixes it finds before reporting done. If it surfaces a new **accuracy** gap that Steps 1–9 missed, treat it as this run's own finding and fix it.

## Output Requirements

Final documentation must be:

- Accurate to the current code and tooling
- Specific: exact commands, file paths, and names
- Navigable, with one home per fact and links instead of copies
- Honest about unknowns
- Reviewed (Step 10) before it is considered final

In the final message, list the files changed with one line each, any code-level findings you did **not** paper over, and the reviewer's result.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Writing from memory or from another project's conventions | Read the source file for each claim first |
| Documenting only the venv path and forgetting ffmpeg, Redis, and Celery | Check the prerequisites row in the coverage table |
| Telling developers to install only `base.txt` and then run tests/lint | `dev.txt` is separate and does not include base |
| Writing endpoint tables by hand | Point to `/api/docs/`; fix serializer/view annotations if the schema is wrong |
| Copying the README's setup into `CLAUDE.md` | Link to it; `CLAUDE.md` is always loaded and budget-constrained |
| Reading or quoting `.env` / `local.py` | Use variable names only |
| Editing `DATABASE_DESIGN.md` from the model docstrings alone | Re-derive from `events/models.py` and migrations |
| Creating `docs/` or `plans/` because another repo has them | This repo's map is above; ask first |
| Stopping after the docs are written | Step 10 is part of finished |

## Exit Criteria

- README lets a new developer get from clone to passing tests and lint without guessing
- Every command, path, env var, setting value, and endpoint named in the docs was checked against code in this run
- `README.md` and `CLAUDE.md` do not contradict each other or `.claude/rules/`
- `.claude/rules/README.md` indexes every rules file
- Code-level problems found along the way are reported, not hidden in the docs
- `documentation-reviewer` has run on this pass's changes and its findings are applied

## Related skills

- [`documentation-reviewer`](../documentation-reviewer/SKILL.md) — invoked as Step 10; also runnable standalone for a scored health check
- [`claude-md-writing`](../claude-md-writing/SKILL.md) — load before editing `CLAUDE.md`, `.claude/rules/*`, or any SKILL.md
- [`django-migration-standards`](../django-migration-standards/SKILL.md) — when a doc change describes migration behavior
- [`portal-code-review`](../portal-code-review/SKILL.md) — for reviewing code changes, not documentation
