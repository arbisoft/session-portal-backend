---
name: task-generator
description: "Generates implementation-ready tasks (title, description, acceptance criteria) from the current staged or unstaged code changes in the Sessions Portal backend (Django 4.2 + DRF, apps `events` and `users`), categorized as API, Data model, Auth & Permissions, Background jobs, Admin, or Infrastructure. Self-heals its own area-detection path table when the repo's layout has moved on."
argument-hint: "Ask to generate tasks from your current changes, or point at a specific diff/commit range/set of files to analyze."
user-invocable: true
---

# Sessions Portal Implementation Task Generator

## Purpose

Analyzes the current code changes (staged, unstaged, or a specified diff/range) in the `arbisoft/session-portal-backend` repo and breaks them into one or more implementation-ready tasks, the kind you would paste into a Taiga user story. Each task has a **Title**, **Description**, and **Acceptance Criteria**, and is categorized by the area of the codebase it touches (**API**, **Data model**, **Auth & Permissions**, **Background jobs**, **Admin**, **Infrastructure**).

This repo is backend-only. Its API is consumed by a separate frontend that lives outside this repo, so there are no Frontend or UI/UX tasks here. A change to a request or response shape is still a requirement on the API task, and the acceptance criteria must state the contract so the frontend owner can act on it.

Every task must read as an unbuilt requirement, not a changelog entry: describe what needs to be implemented, not what was implemented. Never use past tense.

---

# Trigger

Activate this skill when the user says:

- generate tasks / generate implementation tasks
- create tasks from my changes / break down these changes into tasks
- turn this diff into tickets / user stories
- generate tasks for [PR/branch/commit]

---

# Step 1 — Gather the Changes

Staged changes first:

```bash
git diff --staged
git diff --staged --name-only
```

If nothing is staged, fall back to:

```bash
git diff
git diff --name-only
```

If the user names a specific range, PR, or commit, use that instead (`git diff main...HEAD`, `git diff <sha>`, `git show <sha>`, `gh pr diff <n>`). If there is no diff to work from, say so and stop rather than inventing tasks.

Read the changed files, not only the hunks, when a hunk alone does not show the behavior (a serializer `validate_*` method, a permission class, a queryset in a view).

Also get the branch name (`git branch --show-current`). Branches are `<username>/<topic-or-ticket>` and do not reliably carry a ticket number. Reference a Taiga user story only when the user supplies its number or the branch name plainly embeds one, using the PR template's link shape `https://projects.arbisoft.com/project/arbisoft-sessions-portal-20/us/<number>`. Never print the template's `XXX` placeholder and never invent an ID for an individual generated task.

---

# Step 2 — Group Changed Files into Distinct Pieces of Work

Do not produce one task per file, and do not produce one task for the whole diff. Cluster files by what they are _for_: files share a cluster only when they exist to implement the same capability or the same internal concern.

Signals for "same piece of work":

- A model field + its migration + the `DATABASE_DESIGN.md` update + the serializer/view change that exposes it + the tests that cover them → one cluster when the change is small. Split into a **Data model** cluster and an **API** cluster when each half is substantial enough to be reviewed on its own.
- An endpoint's view, serializer, filter, URL entry, `extend_schema` annotation, and its tests in `events/tests/` or `users/tests/` → one cluster.
- A new helper in `events/v1/utils.py` used by exactly one view belongs to that view's cluster. A helper reused by several unrelated endpoints is its own cluster.
- Unrelated one-off fixes (a missing `select_related`, a typo in an error message, a lint cleanup) → their own small clusters. Do not fold them into a larger task to reduce the count.
- Tests ride with the code they cover. A diff that changes only tests (or `conftest.py`/factories) becomes one task per area under test, titled as a requirement ("Add integration tests for ..."), categorized by that area.

Each cluster becomes one task. A large diff can produce many tasks; a small, focused diff can produce just one.

**Folded in, never a task of their own:**

- Migration files under `events/migrations/`: part of the task for the model change that needs them.
- `DATABASE_DESIGN.md` edits that accompany a model change.
- Whitespace-only changes, `.coverage`, `*.log`, and `media/` output.

**Excluded, listed in the summary instead:** changes confined to `README.md`, `CLAUDE.md`, `DATABASE_DESIGN.md` (with no model change), `.claude/**`, or `.github/PULL_REQUEST_TEMPLATE.md`. They fit no category, and documenting already-built behavior is not an unbuilt requirement. If such files are the only change, say so and stop.

---

# Step 3 — Categorize Each Cluster

| Cluster touches | Category |
| --- | --- |
| `events/v1/**` (views, serializers, filters, pagination, URLs, utils), `users/v1/` search/serializers, a new `v2/` package, `arbisoft_sessions_portal/urls.py` | **API** |
| `events/models.py`, `events/migrations/**`, `DATABASE_DESIGN.md` alongside them | **Data model** |
| `users/permissions.py`, `users/v1/views.py` login flows, `arbisoft_sessions_portal/services/google/**`, auth/JWT/CORS/`ALLOWED_HOSTS`/`ALLOW_ONLY_INTERNAL_USERS` settings | **Auth & Permissions** |
| `events/tasks.py`, `events/signals.py`, `events/management/commands/**`, `arbisoft_sessions_portal/celery.py`, ffmpeg handling in `VideoAsset.save()` | **Background jobs** |
| `events/admin.py`, `events/forms.py`, `users/admin.py`, `users/forms.py` | **Admin** |
| `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `.github/workflows/**`, `requirements/**`, `tox.ini`, `pylintrc`, `pytest.ini`, `.coveragerc`, non-auth `settings/**` | **Infrastructure** |

Notes:

- Label by where the change lands for its consumer. A one-field addition threaded model → migration → serializer is a single **API** task. A new constraint or index with no endpoint change is **Data model**.
- A change that alters who can reach an endpoint (adding `IsStaffPermission`, loosening a default) is **Auth & Permissions** even when it lives in an `events/v1/views.py` class. The endpoint's own behavior stays in an **API** task.
- Login and `users/permissions.py` changes are high-scrutiny surfaces under `.claude/rules/security.md`. Say so in the task's Description so the assignee confirms scope before changing them.
- A pure refactor (moving code with no behavior change) keeps the category of the code it moves. Its acceptance criteria say behavior is unchanged and name what must still pass.

**Self-heal check:** if a cluster touches a path this table does not cover (a new app, a renamed package, a new `services/` client), do not guess. Add a row and fix any stale ones in the same pass. To see the current layout: `git ls-files | grep -v migrations`.

---

# Step 4 — Write Each Task as an Unbuilt Requirement

This is the step most likely to go wrong: it is tempting to summarize the diff. Do not. Reframe every sentence from "what the code now does" to "what must be built."

Banned in Title and Description: "added", "fixed", "changed", "updated", "now supports", "refactored to". Use instead: "Implement", "Add", "Build", "Create", "Ensure", "Support", "Extract".

| Diff shows | ❌ Changelog framing | ✅ Requirement framing |
| --- | --- | --- |
| `VideoAssetIncrementViewCountView` + URL | "Added a view count endpoint" | "Implement an authenticated endpoint that atomically increments a video's view count and returns the new total" |
| `Max('events__event_time')` ordering on tags | "Changed tag ordering" | "Order tags and playlists by their most recent event time, with those that have no events listed last" |
| `validate_video_file` on the upload serializer | "Fixed uploads accepting any file" | "Reject uploads whose file extension is not a supported video format, with an error that lists the allowed formats" |

**Description**: 2–4 sentences. State the capability needed and the constraints the diff reveals: who may call it, validation rules, the data source, ordering, side effects, failure behavior. Pull these from what the code actually does; do not invent new ones.

**Acceptance Criteria**: 3–6 concrete, testable bullets derived from the diff's logic. Phrase them as observable behavior a reviewer or QA could verify without reading the code. Avoid restating implementation details such as function or file names. What to look for, by category:

| Category | Look in the diff for |
| --- | --- |
| **API** | Method and path, auth (default `IsAuthenticated` vs staff-only), parser (multipart vs JSON), status codes and validation messages, response fields, pagination, ordering, filters, and the not-found case |
| **Data model** | Field type, nullability and default for existing rows, constraints and indexes, `on_delete` choice, and, when a migration is present, "migration applies cleanly and stays backwards-compatible with the code currently deployed" |
| **Auth & Permissions** | Who is allowed and who is denied (anonymous, non-staff), domain restriction behavior, fields exposed to the client, and what must not change |
| **Background jobs** | Trigger, status transitions, idempotency on retry, failure behavior (what is logged, what state is left), and arguments (IDs, not instances) |
| **Admin** | Who sees the form or action, validation messages, what is enqueued or written on save |
| **Infrastructure** | The observable result: a command or CI job that must pass, a service that must start, an env var name that must be read. Never include secret values |

When the diff shows a list endpoint gaining a related field or a new prefetch, add an acceptance criterion that the query count does not grow with the number of rows. The PR template asks reviewers to consider performance.

---

# Step 5 — Output Format

One block per task, delimited so each is copy-paste-able on its own:

```
### Task N: <Title>
**Category:** API | Data model | Auth & Permissions | Background jobs | Admin | Infrastructure

**Description**
<2-4 sentences>

**Acceptance Criteria**
- [ ] ...
- [ ] ...
- [ ] ...

---
```

Precede the list with a one-line count summary, for example `Generated 3 tasks: 2 API, 1 Auth & Permissions.`

After the list, add one line for anything excluded under Step 2 (for example `Excluded: .claude/** and README.md changes (documentation only).`) and, when the user supplied one, the related Taiga story link.

---

# Example

### Input (subset of a real diff)

- `events/v1/views.py`, `serializers.py`, `urls.py`: new staff-only `POST videoassets/` (multipart) that creates a `VideoAsset` from an uploaded file, rejects extensions other than mp4/mov/avi/webm, derives the title from the filename, and sets `READY` or `FAILED` depending on whether a duration was probed
- Same files: new staff-only `POST /` that takes `video_asset_id` plus metadata (title, description, event time, playlists, tags, presenter ids, optional thumbnail), creates a published session attributed to the requester, and attaches the asset
- `users/v1/views.py`: both login responses gain `is_staff` in `user_info`
- `events/tests/test_staff_apis.py`, `users/tests/test_apis.py`: tests for the above

### Output

```
Generated 3 tasks: 2 API, 1 Auth & Permissions.

### Task 1: Implement a staff-only video upload endpoint
**Category:** API

**Description**
Staff need to upload a video file ahead of creating the event that will
publish it. Implement a multipart endpoint that stores the file as a video
asset not yet attached to any event, derives its title from the uploaded
filename, and records whether processing succeeded. Only the supported video
formats are accepted.

**Acceptance Criteria**
- [ ] Anonymous requests are rejected and authenticated non-staff users receive a 403
- [ ] A request without a `video_file` returns a 400
- [ ] A file whose extension is not mp4, mov, avi, or webm (case-insensitive) returns a 400 whose message lists the allowed formats
- [ ] A valid upload returns 201 with the asset's id, title (filename without extension), and status
- [ ] Status is `READY` when a duration could be determined from the file and `FAILED` when it could not
- [ ] The asset is created without an event

---

### Task 2: Implement a staff-only event creation endpoint
**Category:** API

**Description**
Staff need to publish a session by attaching a previously uploaded, processed
video asset to a new event along with its metadata. Implement an endpoint that
accepts the event details and the asset's id, creates the event as a published
session owned by the requester, and links the asset, optional thumbnail,
playlists, tags, and presenters.

**Acceptance Criteria**
- [ ] Anonymous requests are rejected and authenticated non-staff users receive a 403
- [ ] `video_asset_id` is required; an unknown id returns a 400
- [ ] An asset that is not `READY`, or that already belongs to an event, returns a 400
- [ ] Two simultaneous requests for the same asset cannot both succeed; the second receives a 400
- [ ] Returns 201 with the same event representation as the events list; the event is published, has type session, and its creator is the requesting user
- [ ] Playlists, tags, and presenter ids are optional; duplicate presenter ids produce a single presenter, and a supplied thumbnail replaces the asset's thumbnail

---

### Task 3: Expose the user's staff status in both login responses
**Category:** Auth & Permissions

**Description**
The client needs to know whether the signed-in user may upload videos and
create events so it can show or hide staff actions. Include an `is_staff`
boolean in the `user_info` object returned by both the Google and the
email/password login endpoints. This touches the login flows, a high-scrutiny
surface: confirm the scope before changing them.

**Acceptance Criteria**
- [ ] Google login returns `user_info.is_staff` reflecting the user's staff flag
- [ ] Email/password login returns `user_info.is_staff` reflecting the user's staff flag
- [ ] Existing response fields and the rules for who can log in are unchanged
- [ ] The value is informational only; endpoint access continues to be enforced server-side
```

---

# Best Practices

The skill must:

- Prioritize **clarity** and **testability** in acceptance criteria over exhaustiveness
- Never describe work in past tense; every task reads as something still to be built
- Never invent scope not evidenced in the diff (no acceptance criteria for behavior the code does not show)
- Never invent Taiga ticket IDs or reuse the PR template's `XXX` placeholder
- Never put secret values, tokens, or `.env`/`local.py` contents in a task; name variables only
- Keep each task scoped so it could realistically be assigned to one person and reviewed as one PR
- Report what was excluded rather than silently dropping it
