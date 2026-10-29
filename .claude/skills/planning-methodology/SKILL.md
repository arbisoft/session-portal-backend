---
name: planning-methodology
description: Feature planning methodology for the Sessions Portal backend — ticket analysis, reuse-first research, plan template, and approval workflow. Used by planner-agent to produce implementation plans before coding begins.
---

# Planning Methodology

## Input

One of:
- A Taiga ticket link or ID (the PR template references `projects.arbisoft.com/project/arbisoft-sessions-portal-20/us/<id>`)
- A GitHub issue or PR link
- A branch name that encodes the ticket
- A raw problem description

If you get nothing, ask for one before doing anything else. Do not guess.

## Step 1 — Load the ticket

- **Taiga / other URL** → `WebFetch` (may require auth; if it fails, ask the user to paste the text)
- **GitHub issue / PR** → `gh issue view <n>` / `gh pr view <n>`
- **Raw description** → take it verbatim; do not invent requirements

Capture title and acceptance criteria. Missing AC → list as `[OPEN QUESTION]`, never invent.

## Step 2 — Reuse-first research (small budget)

Use `Grep` / `Glob` / targeted `Read`. Do not scan exhaustively.

1. **Prior art** — an existing util, serializer, filter, view, or model method that already does ≥ 60% of this. Cite `file:function`.
   - `events/v1/utils.py`, `events/v1/filters.py`, `events/v1/serializers.py`
   - `users/permissions.py`, `users/v1/serializers.py`
   - `arbisoft_sessions_portal/services/`
2. **Affected surface** — which endpoints, models, admin forms, Celery tasks, or management commands change.
3. **Existing tests** — files in `<app>/tests/` that already cover this surface. Extend, don't fork.

Conditionally:
- **Migration check** — schema or data change (see `django-migration-standards`).
- **Permission check** — any change to who can reach an endpoint.
- **ffmpeg / upload check** — anything touching `VideoAsset.save()`, uploads, or thumbnails.
- **Search check** — anything touching `EventFilter.filter_search` (trigram threshold, ordering, video-only listing).

## Step 3 — Emit the plan

Use this structure, under ~100 lines:

```
# Plan — <ticket>: <one-line title>

## TL;DR
<2–3 sentences: what, why, where.>

## Ticket
- ID: <Taiga id / #issue / branch>
- Type: feature | bug | refactor | migration | perf | chore
- Apps: events | users | both

## Acceptance Criteria
- [ ] ...
(Missing from ticket → [OPEN QUESTION]; do not invent.)

## Impact
- Blast radius: <endpoints / models / roles / admin flows>
- Data: <tables affected>
- API contract change: <yes/no — fields; versioned as new v2 if breaking>
- High-scrutiny surfaces: <login, permissions, auth settings — or none>

## Reuse
- <file:function> — extend to handle <case>
(None → "No prior art found.")

## Phases

### Phase 1 — <name>
- Files: `events/models.py`, `events/v1/serializers.py`, ...
- Agent: `backend-agent`
- Tests: <files to add/extend>
- Exit: <how we know the phase is done>

## Risks & Open Questions
- [RISK] <what could go wrong, with mitigation>
- [OPEN QUESTION] <needs developer / PM answer>

## Out of Scope
- <thing we're explicitly not doing>

## Rollout
- Migration ordering / backwards compatibility / rollback (if relevant)
```

## Step 4 — STOP and ask

After the plan, ask literally:

```
Do you approve this plan?
- `yes` → hand off to implementation agents
- `revise: <notes>` → I'll update and re-emit
- `reject` → I'll start over with new inputs
```

## Step 5 — Handle the response

- **yes** → "Plan approved. Handing off to <next agent> for Phase 1." Stop. You do not implement.
- **revise: ...** → update the called-out sections, re-emit the full plan, ask again.
- **reject** → ask for new inputs; don't reuse the old plan.

## Hard rules

- Never start implementation. Never auto-proceed.
- Never invent acceptance criteria.
- Never skip the reuse hunt.
- Keep plans under ~100 lines; if bigger, split phases.
- No hedging. Say what should happen and why.
