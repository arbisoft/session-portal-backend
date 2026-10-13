---
name: portal-code-review
description: Use when the user asks to review code, a diff, a pull request, or uncommitted changes in the Sessions Portal backend. Dispatches backend-reviewer-agent, util-reuse-agent, and a review-only dead-code check in parallel, aggregates findings into a paste-ready review with severity labels and impact analysis, then dispatches backend-agent / qa-agent to fix the findings unless the user asks for review only. Grounded in `.claude/rules/`. Not for code outside this repo.
---

# Portal Code Review — Orchestrator Skill

You orchestrate reviews of this Django + DRF backend. You do NOT review or edit the code yourself — you dispatch review agents in parallel, aggregate their findings, then dispatch implementer agents to fix them (Step 7).

Standards live in `.claude/rules/`; checklists in `refs/`. The agents load what they need.

## Step 1 — Orient

1. Resolve scope:
   - **Uncommitted** → `git status`, `git diff`, `git diff --staged`
   - **Branch / PR** → `git diff origin/main...HEAD` (or the PR's base branch; see `.claude/rules/branching.md`)
   - **Specific files** → read them directly
2. Classify changed files:
   - **Backend** → `events/**/*.py`, `users/**/*.py`, `arbisoft_sessions_portal/**/*.py`
   - **Migrations** → `*/migrations/*.py` (backend agent applies extra scrutiny)
   - **Tests** → `*/tests/**`
   - **Dependencies / CI** → `requirements/*.txt`, `.github/**`, `Dockerfile`, `docker-compose.yml`
   - **Docs / config only** → no agents; reply "Docs/config only — no review needed."
3. For a PR, note the ticket link from the PR description. A missing Taiga link is a **NITPICK** in Impact, not a reason to dispatch.
4. Resolve mode. Default is **review + auto-fix** (Steps 1–8). It is **review only** (Steps 1–6) when the user says "review only", "don't fix", or passes `--review-only`, or when the scope is a PR whose branch is not checked out.

## Step 2 — Decide which agents to dispatch

| Condition | Dispatch |
|---|---|
| Any backend file or migration touched | `backend-reviewer-agent` |
| Diff adds a new helper-shaped function (≥ 5 lines: formatter, validator, slug/duration/URL helper, query helper, permission check, API wrapper) | `util-reuse-agent` with the candidate list |
| Any backend file touched | `dead-code-sweep` skill in **review-only mode**, via `subagent_type: general-purpose` |
| `requirements/*.txt` changed | Note in Impact; check the pin against `requirements/base.txt` vs `dev.txt` split yourself |

Detect helper candidates by scanning added `def <name>(...)` lines in `.py` files.

## Step 3 — Dispatch in parallel

Use the `Agent` tool; send all applicable dispatches in one message.

Each prompt includes: the file list (absolute paths) for that agent, the diff source (hunks or the base-branch command), PR title/ticket if known, and the contract "Return ONLY the findings block defined in your agent spec."

For `util-reuse-agent`, include per candidate: `path`, `line`, `name`, `intent`, `signature`.

For `dead-code-sweep`, tell the agent to follow `.claude/skills/dead-code-sweep/SKILL.md` in review-only mode: no deletions, no re-lint, no commit; findings only in the standard `[SEVERITY] path:line — problem` / `Fix:` format.

## Step 4 — Aggregate

1. Order: backend → util reuse → dead code.
2. Within a section: BLOCKER → SUGGESTION → NITPICK.
3. Dedupe identical `[SEVERITY] path:line — problem` lines.
4. Merge all `Missing / Cannot Verify` items into one section.

## Step 5 — Impact analysis (always, produced by you)

One paragraph:

1. **What changed** — the behavioral change in the minimum words.
2. **Blast radius** — endpoints, models, roles, or admin flows affected. Call out login flows, `users/permissions.py`, `VideoAsset.save()`/ffmpeg, the slug signal, and search (`EventFilter.filter_search`) explicitly when touched.
3. **Risk** — migrations, permission changes, serializer field changes (breaking for the web client), Celery task signature changes, anything that can silently change existing data.

If the diff alone cannot establish these, say so and name the files you would need.

## Step 6 — Final output

Use the template in `refs/severity-rules.md`:

```
## Impact
<2–4 sentences>

## Findings
<aggregated findings, sorted by severity>

## Missing / Cannot Verify
- <items>

## Checklist Summary
- Backend: <n findings>
- Util reuse: <n findings | not dispatched>
- Dead code: <n findings>
```

If every agent returned clean:

```
Diff is clean — no findings across backend, util-reuse, or dead-code checks.
```

## Step 7 — Auto-fix

Runs after the Step 6 review is printed. Skip in review-only mode or when the diff is clean.

1. **Triage** every finding:
   - **Fix** — any BLOCKER, SUGGESTION or NITPICK with a concrete `Fix:`.
   - **Hold** — do not fix; list under "Needs your decision":
     - the fix touches a high-scrutiny surface from `.claude/rules/security.md` (login flows, `GoogleUserInfoService`, `users/permissions.py`, JWT/CORS/`ALLOWED_HOSTS`/`ALLOW_ONLY_INTERNAL_USERS`, anything that changes who can reach an endpoint);
     - the fix would change the contract of an existing `v1` endpoint (needs a sibling `v2/` package);
     - the fix needs a product or data decision;
     - every `Missing / Cannot Verify` item.
2. **Dispatch** with the `Agent` tool, in order, because tests depend on final behavior:
   - `backend-agent` — all fixable findings on non-test files, in one prompt.
   - `qa-agent` — fixable findings on tests or missing coverage, after `backend-agent` returns.

   Each prompt carries the findings verbatim (`[SEVERITY] path:line — problem` and `Fix:`), the absolute file paths, and the contract: "Fix only these findings, no unrelated refactors, do not stage or commit, report the files you changed."
3. **Verify** — `tox -e quality` and `pytest --cov --cov-report=term` (or `docker-compose --profile dev up lint test`). On failure, re-dispatch the owning agent with the output; at most 2 rounds. If lint or tests cannot run (no Postgres, missing deps), report them as **not run**, never as passing.
4. **Re-review** — repeat Step 3 for the files the fixes touched only. A finding that returns is fixed once more; if it persists, move it to "Needs your decision" with the reason. Stop when no BLOCKER or SUGGESTION remains.

## Step 8 — Fix report

Use the fix-report template in `refs/severity-rules.md`.

## Do NOT

- Do NOT do the review yourself; dispatch and aggregate.
- Do NOT edit code yourself; fixes go through `backend-agent` and `qa-agent`.
- Do NOT stage, commit, or push fixes; the user decides.
- Do NOT auto-fix held items, and do NOT widen a fix beyond its finding.
- Do NOT serialize dispatches.
- Do NOT post comments to GitHub. Produce the review for the user to paste or approve.
- Do NOT invent severity labels or formats.
- Do NOT pad with praise, apology, or hedging. Silence means pass.

## References

- `refs/backend-checklist.md` — Django/SOLID/ORM/security checklist (backend agent loads)
- `refs/severity-rules.md` — labels, output format, voice (all agents load)
- `.claude/skills/dead-code-sweep/SKILL.md` — dead-code detection
- `.claude/rules/` — authoritative standards
