# Severity Rules & Output Format

Shared by `backend-reviewer-agent`, `util-reuse-agent`, the review-only dead-code check, and the `portal-code-review` skill.

## Severity labels

| Label | Use for |
|---|---|
| **BLOCKER** | Security (auth bypass, PII leak, injection, secrets, unvalidated upload), data loss, migration that breaks the deployed app or is missing for a model change, broken build or tests, LSP violations that break existing callers, a staff-only endpoint reachable by non-staff |
| **SUGGESTION** | SOLID violations, performance anti-patterns (missing `select_related`/`prefetch_related`, N+1, `.save()` on `VideoAsset` where `update()` suffices), missing tests for new logic, DRY / helper duplication, thin-view violations, misleading docstrings or names, dead code |
| **NITPICK** | Naming, import order, minor readability, docstring gaps, misplaced helper scope without a duplicate, missing ticket link |

**Hard rule**: security, auth, or data-loss issues are always BLOCKER, however small.

## Finding format (strict, one per finding)

```
[SEVERITY] <path>:<line> — <one-line problem>
  Fix: <concrete suggestion>. See <spec>.
```

- `<path>` relative to repo root; `<line>` is the post-change line.
- The problem names the rule violated ("SRP", "missing prefetch_related('tags')", "staff endpoint without IsStaffPermission").
- `Fix:` is always present and concrete. "Refactor this" is not a fix.
- `See <spec>` links `.claude/rules/<file>.md` or a skill when it applies.

## Aggregated output

```
## Impact
<2–4 sentences: what changed, blast radius, risk>

## Findings
[BLOCKER] <path>:<line> — <problem>
  Fix: <concrete suggestion>

[SUGGESTION] <path>:<line> — <problem>
  Fix: <concrete suggestion>

[NITPICK] <path>:<line> — <problem>
  Fix: <concrete suggestion>

## Missing / Cannot Verify
- <things that couldn't be checked from the diff alone>

## Checklist Summary
- Backend: <n findings>
- Util reuse: <n findings | not dispatched>
- Dead code: <n findings>
```

## Fix report (after auto-fix)

```
## Fixed
- [SEVERITY] <path>:<line> — <what changed>

## Needs your decision
- [SEVERITY] <path>:<line> — <why it was not auto-fixed>

## Verification
- Lint: pass | fail (<n>) | not run
- Tests: <n passed>, coverage <n>% | not run
- Re-review: clean | <n remaining>

## Files changed
- <path>
```

## Voice

- Direct and terse. No "great work, a few small suggestions".
- One finding per item; no compound "also, also".
- Always pair a problem with a concrete fix.
- Silence means pass: do not list checks that passed.
- Clean diff → one line and stop.

## Do NOT

- Do NOT post comments to GitHub; the user decides what to paste.
- Do NOT suggest `try/except` without a real error-handling gap.
- Do NOT restate `.claude/rules/` — link to it.
- Do NOT invent rules that aren't in `.claude/rules/`; raise them as a discussion point.
- Do NOT flag what pylint, pycodestyle, or isort already catch — CI runs them.
