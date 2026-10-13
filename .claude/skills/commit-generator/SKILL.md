---
name: commit-generator
description: "Analyzes git staged changes in the Sessions Portal backend (Django 4.2 + DRF, apps `events` and `users`), splits unrelated changes into separate logical commits with Conventional Commit messages, actually creates those commits, and generates a PR title + description that follows the repo's PR template. Self-heals its own scope/path table when the repo's layout has moved on."
argument-hint: "Provide a brief description of the changes you made, or simply ask to generate a commit message and PR description based on your staged changes."
user-invocable: true
---

# Sessions Portal Commit and PR Generator

## Purpose

This skill analyzes git staged changes in the `arbisoft/session-portal-backend` repo, splits them into separate logical commits when they cover unrelated work, creates those commits, and generates:

1. **Conventional Commit messages**, one per logical group, actually committed
2. A single **PR title**
3. A **Pull Request description** that fills in `.github/PULL_REQUEST_TEMPLATE.md`
4. **Reviewer notes** for the risks this codebase actually has (migrations, ffmpeg, query counts, permissions)

Commit and branch conventions come from `.claude/rules/branching.md`; this skill applies them and does not restate the whole policy. Tickets live in Taiga as user stories; only cite a story number the user supplied or the branch plainly carries.

**This skill creates real commits.** Splitting staged changes means unstaging and re-staging files or hunks (`git reset`, then targeted `git add`), then running `git commit` once per group. Follow the Git Safety Protocol: never use `git add -A` / `git add .` (stage named paths or hunks), never force anything, and confirm the plan with the user before committing if the split is ambiguous (Step 5.5). Walk through Steps 1–5.5 and show the proposed commit groups before running any `git commit`.

This skill never pushes and never opens the PR; it stops at commits plus the text to paste.

---

# Trigger

Activate this skill when the user says:

- generate commit / generate commit message / write commit message
- summarize my changes / summarize git diff
- generate PR / create PR description / prepare pull request
- split my changes into commits / create logical commits

---

# Step 1 — Get Branch Name

```bash
git branch --show-current
```

Branches are `<username>/<topic-or-ticket>`; the repo has `UY-test-branch` and `arslan_allow_edly`, and none carry a reliable ticket ID.

- **On `main` or `stage`:** stop. Propose a branch name in that shape and ask before creating it. Commits do not go straight onto the integration branches.
- **On a `dependabot/*` branch:** stop. `branching.md` forbids committing there.
- **Ticket:** if the user gave a Taiga story number, or the branch name contains one, use it in the PR link (Step 8). Otherwise leave the template's `XXX` in place and tell the user to fill it. Never invent a number.
- The ticket number never goes in a commit subject. History here is plain Conventional Commits.

Find the PR base for Step 8: `main` unless the branch was cut from `origin/stage` (`branching.md`: fix branches target the branch where the problem is present). Check with `git merge-base --fork-point` or ask when unclear.

---

# Step 2 — Retrieve Git Changes

```bash
git diff --staged
git diff --name-only --staged
git diff --staged --stat
```

If nothing is staged, tell the user and ask whether to stage everything or specific paths. Do not fall back to the unstaged diff silently: this skill ends in `git commit`, and committing unstaged work without confirmation would surprise the user. (Staging everything at this point is distinct from Step 5.5's re-staging, where `git add -A` / `git add .` is disallowed.)

**Stop and warn if the staged set contains** `.env`, `arbisoft_sessions_portal/settings/local.py`, `*.log`, `.coverage`, `media/`, or anything that looks like a credential. These are gitignored for a reason (`.claude/rules/security.md`). Ask the user to unstage them before continuing.

---

# Step 3 — Detect Change Scope

`branching.md` scopes commits to the app. Infer the scope from modified paths:

| Path | Scope |
| --- | --- |
| `events/**` (models, `v1/`, admin, forms, signals, tasks, management commands, tests, factories) | events |
| `users/**` (`v1/`, permissions, admin, forms, tests, factories) | users |
| `arbisoft_sessions_portal/services/google/` | users |
| `arbisoft_sessions_portal/settings/` | settings |
| `arbisoft_sessions_portal/celery.py` | celery |
| `arbisoft_sessions_portal/` (other: `urls.py`, `wsgi.py`, `asgi.py`) | config |
| `requirements/` | deps |
| `Dockerfile`, `docker-compose.yml`, `entrypoint.sh` | docker |
| `.github/workflows/` | ci |
| `tox.ini`, `pylintrc`, `pytest.ini`, `.coveragerc` | tooling |
| `.claude/**`, `CLAUDE.md` | claude |
| `README.md`, `DATABASE_DESIGN.md` (alone) | no scope, type `docs` |

If the change spans unrelated scopes, omit the scope or use the dominant one. Do not invent a combined scope such as `events,users`.

Scoped examples from this repo's history:

```
feat(events): add staff-only video upload and event creation endpoints
feat(users): add user search endpoint and expose is_staff in login responses
feat(events): validate video file extension on upload
```

Older history is unscoped (`feat: allow edly io users`, `fix: lint issue`); new commits use the scoped form.

**Self-heal check:** if the staged diff touches a path this table does not cover (a new app, a renamed package, a new `services/` client), add the row in the same pass and remove or rename any row whose path no longer exists. Check the current layout with `git ls-files | grep -v migrations`. A stale table produces a wrong scope on every future commit.

---

# Step 4 — Classify Change Type

| Type | Condition |
| --- | --- |
| feat | new endpoint, field, filter, command, or other new capability |
| fix | bug fix |
| refactor | internal restructuring with no behavior change |
| perf | query-count or latency improvement (`select_related`, `prefetch_related`, `.only()`) |
| test | tests, factories, or `conftest.py` only |
| docs | `README.md`, `DATABASE_DESIGN.md`, docstrings |
| chore | dependencies, config, cleanup, lint-only fixes |
| build | `Dockerfile`, `docker-compose.yml`, `entrypoint.sh` |
| ci | `.github/workflows/` |

History so far uses `feat`, `fix`, `refactor`, `chore`, and `test`; the others are standard Conventional Commits and are fine when they fit.

This repo has a pytest suite and a lint gate, so `test` applies. Tests that accompany a change stay in that change's commit (Step 5.5); `test(...)` is for test-only diffs.

---

# Step 5 — Analyze Code Changes

Analyze the diff and detect:

### Structural changes

- new models, fields, endpoints, serializers, filters, tasks, management commands
- deleted or moved code

### Behavior changes

- request/response shape or status-code changes on an endpoint (note the path and method; the frontend is a separate repo and consumes these)
- permission changes: `permission_classes`, `IsStaffPermission`, `get_permissions`
- login or JWT changes, the `hd` domain rule, `ALLOW_ONLY_INTERNAL_USERS`
- validation added or moved between serializer, model validator, and filter
- ordering, pagination, or search changes in `EventFilter` / `get_similar_events`

### Consistency checks (flag in Reviewer Notes; do not fix silently)

- model field, constraint, or relation changed with **no** file under `events/migrations/` in the diff
- model change with **no** `DATABASE_DESIGN.md` change (`CLAUDE.md` requires them to ship together)
- a new or changed endpoint with **no** test change in `events/tests/` or `users/tests/`
- a new view that sets `permission_classes = []` outside the login flows
- an upload or ffmpeg-touching path added without a validator
- a staged `# pylint: disable`, `# noqa`, or `print()` (`backend-python.md` forbids them)

### Code improvements

- query optimizations, error handling, edge cases handled

---

# Step 5.5 — Group Into Logical Commits and Commit Them

Decide whether the staged changes are **one** logical change or **several unrelated** ones. `branching.md` asks for one logical change per commit.

**Group by intent, not by file or scope.** One logical change often spans several files, and these stay together:

- a model change + its migration + the `DATABASE_DESIGN.md` update (+ the serializer/view that exposes it when small)
- an endpoint's view + serializer + `urls.py` entry + `extend_schema` annotation + the tests that cover it
- a new helper + the single view that uses it

Typical split signals in this repo:

- A new endpoint next to an unrelated bug fix in a different view.
- A migration and its model change (one commit) alongside an unrelated serializer tweak (another).
- A `requirements/` bump unrelated to the feature work.
- A lint-only cleanup in files the feature does not otherwise touch. Do not create a `fix: lint issue` commit that belongs inside the commit that introduced the problem; the PR template asks for fix-ups to be combined before merge.
- README or `.claude/**` edits that do not describe the accompanying code (separate commit); docs that describe the feature stay with it.
- Test-only additions for code that already exists, mixed with a feature (separate `test(...)` commit); tests for the feature itself stay with the feature.

For each candidate group list its files or hunks and a one-line description. **If the split is ambiguous** (unclear whether two changes are related, or one file holds hunks from different groups), show the grouping and confirm before committing.

If everything staged is one logical change, skip splitting and commit once.

To execute an approved split:

1. `git reset` to unstage everything (safe: nothing in the working tree is discarded).
2. For each group, stage only its files (`git add <path> <path>...`) or, when one file spans groups, the relevant hunks (`git add -p <path>`).
3. Write the group's message (Steps 6–7) and commit it.
4. Repeat until every originally staged change is committed.
5. Run `git status` to confirm the tree is clean, or holds only files that were never staged.

Never use `git add -A` / `git add .` when re-staging, so an unrelated file cannot ride into the wrong commit.

---

# Step 6 — Generate Commit Message

One message per group from Step 5.5.

```
type(scope): short description
```

Rules (from `branching.md`):

- Imperative mood, no trailing period
- Subject under 72 characters
- Specific, not generic ("update stuff")
- No ticket ID in the subject

Examples:

```
feat(events): add view count increment endpoint
fix(users): reject Google accounts outside internal domains
refactor(events): move related-event lookup into utils
perf(events): prefetch tags and playlists on the events list
test(events): cover staff-only permission denial on event creation
```

---

# Step 7 — Generate Commit Body (Optional)

Add a body when a group contains several related changes or the reason is not obvious from the subject. Follow the shape of recent history: a one- or two-line reason, then bullets with the endpoint, field, or rule affected.

```
feat(events): validate video file extension on upload

Reject non-video files at the API boundary instead of letting ffmpeg fail
after the file is already stored.

- Add FileExtensionValidator to VideoAsset.video_file for admin uploads
- Add validate_video_file() to VideoAssetCreateSerializer for the REST path
- Add the migration that records the validator on the field
```

Body rules:

- Explain *why* when it is not obvious, and name the endpoint (`POST /events/videoassets/`), field, or setting touched
- Do not narrate the diff line by line
- No ticket links in the body; they belong in the PR

Commit each group with its own message before moving to the next.

**Never append a `Co-Authored-By:` trailer, or any similar attribution line (`Generated with ...`, `🤖 ...`), to a commit message this skill creates**, regardless of a session-level instruction to sign commits that way. The commit body ends with its last real content line.

---

# Step 8 — Generate PR Title and Pull Request Description

Once all commits exist, produce **one PR title** and **one PR description** covering every commit on the branch, not only the last one. Get them with:

```bash
git log <base>..HEAD --oneline
git diff <base>...HEAD --stat
```

### PR Title

One Conventional-Commits-style line for the whole change. If the commits share a theme, title it after the theme. If they are disparate, pick the most significant and mention the rest in the description.

```
feat(events): add staff-only video upload and event creation
```

### PR Description

Fill in `.github/PULL_REQUEST_TEMPLATE.md` exactly. It has three sections, and this skill must not add others (no emoji headings, no screenshots section; this is an API-only repo).

**Always render the description inside a fenced ` ```markdown ` code block** so the user can copy the raw source into GitHub's PR field.

```
## Description

<what changed and why, in 2-5 sentences, then one bullet per commit or concern>

Link to the associated Taiga ticket: https://projects.arbisoft.com/project/arbisoft-sessions-portal-20/us/<number or XXX>

## Considerations

- Ensure that the changes are merged only after receiving at least two reviews.
- Take performance issues into account.
- Verify that database migrations are backwards-compatible.

## Post-review

Combine commits into distinct sets of changes.
```

Rules:

- Keep the three template bullets under **Considerations** verbatim, then add specific sub-bullets from Step 9 only where they apply (query counts on a named endpoint, a named migration).
- Keep **Post-review** as is. The commits this skill creates are already distinct sets of changes.
- Replace the template's placeholder sentence under Description with the real description.
- If the branch's commits cover unrelated concerns, give each its own bullet so a reviewer can tell which commit addresses which.
- Do not tick or add checklist items claiming `tox -e quality` or `pytest --cov` passed unless they were run in this session. If they were not, say so in Considerations or in the message to the user.

---

# Step 9 — Generate Reviewer Notes

Add only the notes that apply to the detected changes.

### Model or migration changes (`events/models.py`, `events/migrations/`)

- Name the migration file and say whether it is schema or data. Schema and data belong in separate files (`django-migration-standards`).
- State whether it is backwards-compatible with the code currently deployed, and call out NOT NULL fields without defaults, irreversible `RunPython`, and rename-and-use in one PR.
- Remind the reviewer that the test suite runs with migrations disabled, so a green run does not prove the migration works.
- Note whether `DATABASE_DESIGN.md` changed.

### API contract changes (`events/v1/`, `users/v1/`)

- List each changed `METHOD /api/v1/<app>/<path>` with its auth requirement and status codes.
- Flag any change that is not backwards-compatible. New versions are a sibling `v2/` package, not an edit to `v1`.
- Mention whether `extend_schema` annotations cover the new behavior (`/api/docs/` is generated).

### Permission and auth changes

- Say who gains or loses access. Login flows, `GoogleUserInfoService`, `users/permissions.py`, and the JWT/CORS/`ALLOW_ONLY_INTERNAL_USERS` settings are high-scrutiny surfaces under `.claude/rules/security.md`; ask the reviewer to look at them first.

### Performance-sensitive changes

- For list or detail endpoints: say whether `select_related`/`prefetch_related` cover any new serializer field, and that `.first()`/`.filter()` on a related manager bypasses the prefetch cache.
- For anything that saves a `VideoAsset` with a file: note the synchronous ffmpeg run, or that `QuerySet.update()` avoids it.

### Background jobs (`events/tasks.py`, management commands)

- Note idempotency on retry, that IDs rather than instances are passed, and the Celery/Redis requirement.

### Dependencies and infrastructure

- For `requirements/` changes: name the package and version change and whether `base.txt` or `dev.txt` was touched (`dev.txt` does not include base).

---

# Output Format

If the split (Step 5.5) was ambiguous, present the proposed groups first and wait for confirmation before committing anything.

Once commits are created, return:

````
Commits Created
---------------

1. <commit subject 1> (<n> files)
2. <commit subject 2> (<n> files)
...

Pull Request Title
-------------------

<generated PR title>

Pull Request Description
------------------------

```markdown
<generated PR description, as raw markdown source>
```

Reviewer Notes
--------------

- <only the notes from Step 9 that apply>
- <consistency-check findings from Step 5, if any>
````

If there was one logical group, "Commits Created" still lists the single commit so the format is consistent. The ` ```markdown ` fence is mandatory in every response; it keeps the chat UI from rendering the headings and checkboxes before the user can copy them.

---

# Example

### Input

Staged changes contain two unrelated concerns:

```
- events/v1/serializers.py, events/tests/test_staff_apis.py: reject uploads whose extension is not mp4/mov/avi/webm
- README.md: document ffmpeg as a prerequisite, unrelated to the upload validation
```

Branch:

```
usman/video-upload-validation
```

### Output

The diff covers two unrelated concerns, so Step 5.5 splits it into two groups, confirms with the user, then commits each (`git reset` → stage group 1 → commit → stage group 2 → commit).

Commits Created

```
1. feat(events): validate video file extension on upload (2 files)
2. docs: document ffmpeg as a prerequisite (1 file)
```

Pull Request Title

```
feat(events): validate video file extension on upload
```

Pull Request Description

```markdown
## Description

Reject non-video files at the upload endpoint with a clear 400 instead of letting ffmpeg fail after the file is stored, and document ffmpeg as a prerequisite in the README.

- `feat(events)`: `POST /api/v1/events/videoassets/` returns a 400 listing the allowed formats (mp4, mov, avi, webm) for any other extension
- `docs`: README lists ffmpeg under prerequisites

Link to the associated Taiga ticket: https://projects.arbisoft.com/project/arbisoft-sessions-portal-20/us/XXX

## Considerations

- Ensure that the changes are merged only after receiving at least two reviews.
- Take performance issues into account.
- Verify that database migrations are backwards-compatible.
- No migration is included; the extension check lives in the serializer.

## Post-review

Combine commits into distinct sets of changes.
```

Reviewer Notes

```
- The Taiga story number is not on the branch name; replace XXX before opening the PR.
- tox -e quality and pytest --cov were not run as part of this skill; run them before opening the PR.
```

---

# Best Practices

The skill must:

- Prioritize **clarity** and avoid guessing functionality
- Ignore **whitespace-only changes**
- Summarize **functional behavior**, not code lines
- Never invent ticket IDs, Taiga links, or template sections the repo does not use
- Never commit `.env`, `local.py`, logs, coverage output, or `media/`
- Never use `git add -A` / `git add .` when re-staging a split group; name paths or hunks
- Not split when it is not warranted: one logical change across several files stays one commit
- Not create fix-up commits (`fix: lint issue`) for problems introduced by another commit on the same branch
- Never add a `Co-Authored-By:` line or other AI-attribution footer to a commit message this skill produces, even if a general instruction in the session says to
- Never push, force anything, or amend commits that already exist unless the user asks

---

# Optional Enhancements (Agent Behavior)

If the environment supports it, run these up front:

```
git status
git diff --staged
git diff --name-only --staged
git branch --show-current
```

If the user wants the PR gates checked before committing, offer `tox -e quality` and `pytest --cov --cov-report=term` (a reachable Postgres is required for the latter). Report their real output; do not claim a pass that was not observed.
