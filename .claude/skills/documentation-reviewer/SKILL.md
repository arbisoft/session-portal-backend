---
name: documentation-reviewer
description: Review the Sessions Portal backend's documentation (README.md, CLAUDE.md, DATABASE_DESIGN.md, .claude/rules/, PR template) against the actual Django 4.2 + DRF code, tooling config, and generated OpenAPI schema, and repair gaps that are missing, incomplete, inaccurate, or unclearly worded. Checks wording, grammar, and terminology consistency in addition to factual accuracy. Runs automatically as documentation-generator's final step, or standalone for a scored health check. Self-heals its own SKILL.md when the file lists or facts it cites drift from the repo.
user-invocable: true
---

# Documentation Reviewer

> **What this skill does:** audits this repo's documentation and repairs it. It checks facts (missing, incomplete, inaccurate against the code) and prose (unclear wording, grammar, inconsistent terms), scores each area, then edits the files that need it.
>
> **When to use this vs. `documentation-generator`:**
>
> - `documentation-generator` calls this skill automatically as its Step 10, scoped to the files it just changed. You do not need to run this separately after a generator pass.
> - Run this skill **standalone** for a scored health check across the project with no specific trigger: docs are suspected stale, or a periodic audit.
> - Use the generator when the trigger is a specific code change and you want the generate-then-review pipeline in one go.

## Scope Options

| Invocation | What it reviews |
| --- | --- |
| `/documentation-reviewer` | Full audit: README, CLAUDE.md, DATABASE_DESIGN.md, `.claude/rules/`, PR template |
| `/documentation-reviewer readme` | `README.md` only |
| `/documentation-reviewer setup` | README setup, env vars, Docker, prerequisites against `Dockerfile`, `docker-compose.yml`, `settings/`, `requirements/` |
| `/documentation-reviewer api` | Endpoint mentions in any doc, plus `extend_schema` coverage, against the three `urls.py` files and the views |
| `/documentation-reviewer data-model` | `DATABASE_DESIGN.md` against `events/models.py` and migrations |
| `/documentation-reviewer agent-docs` | `CLAUDE.md` and `.claude/rules/*.md` against tooling and code |
| _(chained, no slash command)_ | Exactly the files `documentation-generator` just touched. Skip Phase 1 discovery; still run Phases 3, 5, 6, 7 on that set |

No scope given → full audit.

## Workflow

```
Phase 1: Discovery      → Find docs and source-of-truth files
Phase 2: Understanding  → Confirm the project facts below still hold
Phase 3: Audit          → Score coverage, accuracy, and prose
Phase 4: Health Report  → Findings and repair plan
Phase 5: Repair         → Edit the files with gaps
Phase 6: Validation     → Cross-check repaired docs against code
Phase 7: Output         → Final report
```

---

## Phase 1: Discovery

### 1a. Documentation files

```bash
git ls-files | grep -E "\.md$"
```

Docs this project maintains:

```
README.md
CLAUDE.md
DATABASE_DESIGN.md
.github/PULL_REQUEST_TEMPLATE.md
.claude/rules/README.md          # index of the rules files
.claude/rules/backend-django.md
.claude/rules/backend-python.md
.claude/rules/solid.md
.claude/rules/security.md
.claude/rules/testing.md
.claude/rules/branching.md
```

There is **no** `docs/`, `plans/`, `CHANGELOG.md`, or `CONTRIBUTING.md`. Do not create them without the user asking. Skill, agent, and command files under `.claude/skills|agents|commands/` are instruction files, not project docs: review them only when a doc claim contradicts them (use `claude-md-writing` to edit).

### 1b. Source-of-truth files

Read what your scope needs before writing a single line.

**Tooling and config**

```
requirements/base.txt, requirements/dev.txt   → dependencies (dev.txt does NOT include base.txt)
tox.ini                                        → envs: quality, isort, isort-check; isort sections; pycodestyle
pylintrc                                       → pylint limits and plugins
pytest.ini, .coveragerc                        → test settings module, fail_under
.github/workflows/ci.yml                       → what CI runs and on what
.github/workflows/build-and-push-container-image.yml  → image build on release
Dockerfile, docker-compose.yml, entrypoint.sh  → targets (app, dev), services (db, redis, django, celery, lint, test)
```

**Settings and environment**

```
arbisoft_sessions_portal/settings/base.py          → env var reads, CORS, JWT, Celery, logging, ALLOW_ONLY_INTERNAL_USERS
arbisoft_sessions_portal/settings/test.py          → test DB defaults, memory:// broker, DisableMigrations
arbisoft_sessions_portal/settings/local.example.py → what local.py should contain
arbisoft_sessions_portal/celery.py
```

Never open `.env` or `settings/local.py`. They are gitignored and may hold secrets.

**Application code**

```
arbisoft_sessions_portal/urls.py, events/v1/urls.py, users/v1/urls.py   → real routes
events/v1/views.py, users/v1/views.py, */serializers.py                 → behavior, auth, schema annotations
events/models.py, events/migrations/                                    → data model
events/tasks.py, events/signals.py, events/admin.py, events/forms.py
events/management/commands/                                             → check_videoasset_status, prepopulate_events
users/permissions.py, arbisoft_sessions_portal/services/google/
*/tests/conftest.py, */factories.py                                     → fixtures the testing docs refer to
```

**Self-heal check:** if a listed file no longer exists, or a real file in one of these categories is missing from the list (a new app, a new `docs/` folder, a new rules file), update this phase of the SKILL.md in the same pass.

---

## Phase 2: Project Understanding

Confirm these still hold before relying on them. If one is false, fix this section first (self-heal).

```
Project: Arbisoft Sessions Portal backend
Type: REST API (Django 4.2 + DRF), PostgreSQL required (django.contrib.postgres, pg_trgm). No frontend in this repo.
Apps: users (no models; django.contrib.auth.User), events (Event, Tag, Playlist, VideoAsset, EventPresenter)
API: /api/v1/users/, /api/v1/events/; generated docs at /api/schema/, /api/docs/, /api/redoc/ (drf-spectacular)
Auth: JWT (simplejwt) + session auth; IsAuthenticated default; Google OAuth token or email/password login
Background work: Celery + Redis, only for Google Drive video imports
External binaries: ffmpeg (VideoAsset.save() runs it synchronously)
Python 3.12; Postgres 16 in compose and CI
Quality gate: tox -e quality (pylint, pycodestyle, isort --check over events users); pytest --cov with fail_under = 80
Deploy: image built and pushed on a published GitHub release (workflow also has manual dispatch); no ops runbook in this repo
Audience: new backend developers (README) and AI coding agents (CLAUDE.md, rules)
Not relevant: mobile, frontend, native builds, a production operations runbook
```

---

## Phase 3: Coverage and Quality Audit

For each area decide: does it exist, is it **accurate** (checked against Phase 1b), **complete**, **clear** for a newcomer and trustworthy for an existing engineer, and **well written**.

### Coverage checklist

Mark each **Present**, **Partial**, **Missing**, or **N/A**.

| Area | Expected location | Status | Notes |
| --- | --- | --- | --- |
| Project overview and stack | `README.md`, `CLAUDE.md` → Project | | |
| Prerequisites (Python, Postgres, ffmpeg, Redis, Docker) | `README.md` | | ffmpeg and Redis/Celery are easy to miss |
| Install steps (base vs dev requirements) | `README.md` | | `dev.txt` does not include base |
| Environment variables | `README.md` | | Names from `base.py`, `test.py`, `docker-compose.yml` |
| `local.py` setup | `README.md` | | `cp settings/local.example.py settings/local.py` |
| Run server / Celery worker | `README.md`, `CLAUDE.md` → Commands | | |
| Tests and coverage gate | `README.md`, `.claude/rules/testing.md` | | |
| Lint commands | `README.md`, `CLAUDE.md`, `.claude/rules/backend-python.md` | | Must match `tox.ini` |
| Docker usage | `README.md` | | Compose file is `docker-compose.yml` |
| Architecture and traps | `CLAUDE.md` | | |
| Data model | `DATABASE_DESIGN.md` | | |
| API reference | Generated; docs point to `/api/docs/` | | Not hand-written |
| Contribution workflow | `.claude/rules/branching.md`, PR template | | |
| Security rules | `.claude/rules/security.md` | | |
| Rules index | `.claude/rules/README.md` | | Lists every rules file |
| CHANGELOG | n/a | N/A | Git history and PRs are the record; do not create one unprompted |

### Quality audit

For each **Present** or **Partial** doc:

- Broken links, placeholder text, or references to files that no longer exist?
- Commands accurate? Verify tox env names, compose service/profile names, `manage.py` commands, Celery app name (`arbisoft_sessions_portal`)
- Env vars accurate? Verify the set and which file reads each. `DJANGO_PORT` is read only by `docker-compose.yml`, not by Python
- Versions accurate? Python and Postgres versions agree across README, `Dockerfile`, `docker-compose.yml`, `ci.yml`
- Settings values accurate (CORS origin, JWT lifetimes, `ALLOW_ONLY_INTERNAL_USERS`, Celery defaults, logger name `asp_api`)?
- Endpoint paths, methods, and auth accurate? Cross-check the three `urls.py` files, then the view's `permission_classes` / `get_permissions`
- Model, field, and relation names accurate against `events/models.py` **and** migrations? (`DATABASE_DESIGN.md` predates some fields)
- Does a doc describe something that no longer exists, or omit something that does?
- Does the doc separate a **deliberate convention** from a gap? Do not "fix" these: `on_delete=DO_NOTHING` on `Event` FKs with deletion disabled in admin, tests running with migrations disabled, slug assignment in a `post_save` signal, ffmpeg errors logged rather than raised, `CELERY_BROKER_URL` defaulting to the compose hostname `redis`

### Known drift to check first

Snapshot taken 2026-10-13. Verify each before acting, and delete an entry once it is fixed.

| Where | Observed | Truth source |
| --- | --- | --- |
| `settings/base.py` | `DEBUG = os.getenv("DJANGO_DEBUG", False)` is truthy for any non-empty string. README and `CLAUDE.md` warn about this as current behavior; the code is unchanged | Code finding: report it, and do not rewrite the docs as if `DJANGO_DEBUG=False` worked |
| `events/tests/test_filters.py:137` | `test_events_search_filter_fuzzy_matching_description` is 52 characters; the 50-character test-name limit is a house convention that pylint does not enforce | `pylintrc`, `.claude/rules/testing.md` |

### Wording, Grammar, Clarity & Consistency Audit

A doc can be factually right and still fail this pass. Run it on every Present/Partial doc touched:

- **Grammar and spelling** — read as prose, not as a diff. Respect the established voice (terse, imperative, code-adjacent) of each file before "correcting" it
- **Terminology** — one word per concept. This repo's vocabulary: *Event*, *VideoAsset* (not "video" when the model is meant), *tag*, *playlist*, *presenter*, *staff* (`is_staff`) vs *superuser*, *staff-only endpoint* (gated by `IsStaffPermission`), *internal user* (`hd` is `arbisoft.com` or `edly.io`). Flag a doc that uses two words for one thing or reuses a term loosely
- **Clarity** — read as a newcomer (do I know what to *do*?) and as an engineer skimming for one fact (can I trust it without reading the section?)
- **Actionability** — name the command, file, or value (`tox -e quality`, not "run the linter")
- **Structure** — heading depth, list style, and code-fence language tags match the rest of the file and its siblings. Existing README uses `$` prompts in bash blocks; follow the file's own convention
- **Orphans** — no TODO markers, half sentences, `TBD`, empty headings
- **Acronyms** — expand on first use per file (JWT, OAuth, ffmpeg is fine as a tool name, `pg_trgm`)
- **Comments in code samples** — rules files forbid narrating `#` comments in code; sample code in docs should follow suit

Report these findings the same way as accuracy findings, with `file:line` evidence.

---

## Phase 4: Health Report

Produce this before repairing anything.

```
## Documentation Health Report
Date: [today]
Project: Sessions Portal backend
Scope: [Full / specific area]

### Quality Scores

| Area | Score (Good / Needs Work / Poor) | Finding |
|------|----------------------------------|---------|
| README.md | | |
| CLAUDE.md | | |
| DATABASE_DESIGN.md | | |
| .claude/rules/*.md | | |
| PR template | | |
| API schema inputs (extend_schema) | | |

### Gaps Found

Missing:      [files or sections that do not exist]
Incomplete:   [files and specific sections]
Outdated:     [what is wrong → correct value, file:line]
Unclear:      [wording/consistency issues, file:line]
Code issues:  [doc/code disagreements where the code looks wrong; reported, not fixed in the doc]

### Repair Plan

Update:       [files]
Create:       [files]
No action:    [files]

### Estimated scope
[Small: 1-2 files / Medium: 3-5 / Large: 6+]
```

**Large scope:** confirm with the user before repairing. **Small/Medium:** proceed.

---

## Phase 5: Repair

Edit files in place. Every statement must trace to a file you read in this run.

### 5a. README.md

Preserve the existing order and tone. Required sections, adding only what is missing:

```
# Arbisoft Sessions Portal            (badges and one-line purpose)
## Prerequisites                       Python 3.12, PostgreSQL 16, ffmpeg, Redis (Drive imports), Docker (optional)
## Set up Environment Variables        .env with the DB_* and DJANGO_* names
## Code setup                          local.py from local.example.py
## Option 1: Virtual Environment       pyenv, install requirements, createdb, migrate, runserver
## Option 2: Docker                    export GID/UID, docker-compose up --build
### Run Linting / Run Tests            tox -e quality; pytest --cov --cov-report=term; compose --profile dev
## Celery worker                       only for Google Drive downloads
## API documentation                   /api/docs/, /api/redoc/
```

Rules:

- Commands must match `tox.ini`, `docker-compose.yml`, and `ci.yml` exactly
- Env var names must match what `base.py`, `test.py`, and `docker-compose.yml` read; never put real values from `.env`
- State which requirements file a given task needs
- Do not promote anything to "supported" that the code does not do

### 5b. CLAUDE.md

Always loaded, so the budget rules in `claude-md-writing` apply in full. Before editing:

1. Load `claude-md-writing`
2. Verify each existing claim (commands, trap descriptions, file paths) against Phase 1b files and fix the ones that are wrong
3. Add a line only if it changes behavior and is not a linter's job; link to README or a rules file for procedures

### 5c. API documentation

There is no `docs/api.md`. When a doc names an endpoint, correct the path/method/auth against the `urls.py` files and views. If the *generated* schema would be wrong (a custom `APIView` without `extend_schema`, an unusual response), report it as a finding with the view and line. Changing views is not a documentation task, so do not do it here.

### 5d. DATABASE_DESIGN.md

Keep the Mermaid `erDiagram` block and its commented-out Workstream TODO (a planned design, not drift). Re-derive entities from `events/models.py` and migrations:

- Add fields that exist (`slug`, `view_count`, `captions_file`, and so on) and drop ones that do not
- Reflect how relations are actually modeled (implicit M2M for tags/playlists, explicit `EventPresenter` through model with `unique_together`)
- Keep `on_delete` choices visible if the diagram shows relations
- If the file stays intentionally "intended schema", say so in a one-line note at the top rather than silently mixing intended and actual

### 5e. .claude/rules/*.md

Verify against tooling, not just against each other:

- Lint limits and tools against `pylintrc` and `tox.ini`
- Coverage gate against `.coveragerc`
- Fixture and factory names against `events/tests/conftest.py`, `events/factories.py`, `users/factories.py`
- Branch and release statements against `git branch -a` and the workflows
- `.claude/rules/README.md` table lists every file in the directory

These files are instruction files: apply `claude-md-writing`'s cross-cutting rules (specific, no linter's-job instructions).

### 5f. CHANGELOG / CONTRIBUTING

Do not create. If the user asks for a changelog, base entries only on real commits (`git log --oneline --no-merges`).

---

## Phase 6: Consistency Validation

```bash
cat tox.ini pylintrc .coveragerc pytest.ini
cat requirements/base.txt requirements/dev.txt
grep -n "getenv\|environ" arbisoft_sessions_portal/settings/*.py   # do not print local.py values
grep -n "path(" arbisoft_sessions_portal/urls.py events/v1/urls.py users/v1/urls.py
grep -n "^class \|permission_classes\|get_permissions" events/v1/views.py users/v1/views.py
ls events/management/commands events/migrations
```

Verify:

- [ ] Every command in docs exists (tox env, compose service/profile, management command, Celery app name)
- [ ] Every env var documented is read somewhere (`base.py`, `test.py`, `local.example.py`, `docker-compose.yml`); none is missing from the README
- [ ] Python and Postgres versions agree everywhere they appear
- [ ] Every documented endpoint exists with the stated method and auth
- [ ] Every model, field, and relation named matches `events/models.py` and migrations
- [ ] No doc names a file, folder, or class that is gone (`git status` for `D`/`R`)
- [ ] `README.md` and `CLAUDE.md` do not contradict each other or `.claude/rules/`
- [ ] `.claude/rules/README.md` indexes every rules file
- [ ] Links resolve; no secrets or `.env` values appear in any doc
- [ ] Every doc touched also got the Wording, Grammar, Clarity & Consistency pass

Fix inconsistencies before proceeding. If the **code** looks wrong rather than the doc, report it as a finding instead of editing the doc to match.

---

## Phase 7: Final Output

```
## Documentation Review: Final Report
Date: [date]
Scope: [Full / specific area]

### Quality Scores
| Area | Before | After |
|------|--------|-------|
| README.md | | |
| CLAUDE.md | | |
| DATABASE_DESIGN.md | | |
| .claude/rules/*.md | | |

### Files Created
- [path: what and why]

### Files Updated
- [path: what changed and why]

### Files No Action Required
- [paths]

### Code Findings (not fixed in docs)
- [file:line: issue]

### Remaining Gaps
- [anything that needs information only the maintainers have]
```

Files are edited in place. Do not paste whole files into the report unless the user asks.

---

## Self-Healing This Skill File

This SKILL.md is itself a claim about the repo: its file lists (Phase 1), project facts (Phase 2), known-drift table (Phase 3), and doc shapes (Phase 5) can go stale.

- When something this file states as fact no longer holds, fix that part of the file in the same pass
- Scope the fix to what you observed; do not rewrite sections you did not check
- Remove "Known drift" rows once fixed; add rows for new drift you could not fix this run
- If the drift changes the audit's scope (a new app, a new `docs/` folder), say so in the Health Report

## Guardrails

**Do:**

- Base every statement on a file you read in this run
- Preserve existing structure and voice when updating a partial doc
- Distinguish deliberate conventions from gaps
- Keep one home per fact; link instead of copying
- Report code problems you find, with `file:line`

**Do not:**

- Document endpoints, commands, env vars, or fields that do not exist
- Open or quote `.env` or `settings/local.py`
- Hand-write an API reference or add an ops/deployment runbook
- Create `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/`, or `plans/` unprompted
- Rewrite accurate docs
- Edit a doc to match code that looks broken
- Make code changes; this skill edits documentation only

## Relationship to Other Skills

| Skill | Purpose | When |
| --- | --- | --- |
| **documentation-reviewer** (this) | Scored audit and repair, including the prose pass | Standalone health check, or chained from the generator |
| **documentation-generator** | Inventory → generate/repair → validate → hand off to this skill | A specific change made docs stale |
| **claude-md-writing** | Authoring rules for `CLAUDE.md`, `.claude/rules/*`, SKILL.md | Any edit to those files |
| **portal-code-review** | Review code changes | Before merging a PR |
| **django-migration-standards** | Migration rules | When a doc change describes migration behavior |
