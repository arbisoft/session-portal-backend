---
name: util-reuse-methodology
description: DRY / duplicate-helper detection methodology for the Sessions Portal backend — search order, overlap scoring, placement rules, and output format. Used by util-reuse-agent to find and flag duplicate utilities.
---

# Util Reuse Methodology

## Inputs

A list of candidate helpers:

```
- path: <file>
  line: <line>
  name: <function name>
  intent: <3-5 word summary>
  signature: <params and return shape>
```

If intents are missing, infer them from the name and body.

## Step 1 — Search in priority order

1. `<same-app>/v1/utils.py`
2. `<same-app>/v1/filters.py`, `<same-app>/v1/serializers.py` (shared validators, mixins, base serializers)
3. Model methods and properties in `<same-app>/models.py`
4. `users/permissions.py` for permission checks
5. `arbisoft_sessions_portal/services/` for external-system clients (Google)
6. The other app's equivalents (`events` ↔ `users`)
7. `events/factories.py` / `users/factories.py` — only for test-helper candidates
8. Repo-wide `Grep` by behavior: distinctive string literals, regexes, constants, and the core verb + noun (`slug`, `duration`, `drive`, `thumbnail`, `search`)

Skip `migrations/`, `__pycache__`, and `.tox`.

## Step 2 — Score each hit

- **≥ 80% overlap** → duplicate; suggest direct reuse.
- **50–80%** → close; suggest extending the existing helper.
- **< 50%** → not a duplicate; don't flag.
- **No hit** → check placement:
  - Used by one module → keep in that module's `utils.py`.
  - Used by both apps → belongs in a shared location, not inside one app's `v1/utils.py`.
  - Single-use helper that will not be reused → inline is fine; don't flag.

## Step 3 — Cite precisely

Every finding names the new `file:line`, the existing `file:function`, the classification (duplicate / close), and a concrete fix ("import and reuse X" or "extend X to handle Y"). Never flag without citing the specific existing function.

## Step 4 — Output (strict)

```
## Util Reuse Review

[SUGGESTION] <new-file>:<line> — Duplicate of <existing-file>:<existing-fn>.
  Fix: import and reuse `<existing-fn>`. If this case isn't covered, extend it rather than creating a parallel one.

[SUGGESTION] <new-file>:<line> — Close match to <existing-file>:<existing-fn> (~60% overlap).
  Fix: extend `<existing-fn>` to handle <the new case>, or document why a separate helper is warranted.

[NITPICK] <new-file>:<line> — Helper placed in one app but used by both.
  Fix: move to a shared module so both apps can import it.
```

If nothing duplicates:

```
## Util Reuse Review
Clean — no duplicate utilities found.
```

## Severity

- **SUGGESTION** — duplicate or close match with a concrete citation.
- **NITPICK** — misplaced helper without an existing duplicate.
- Never **BLOCKER**.

## Do NOT

- Flag a duplicate without naming the exact existing file and function.
- Review style, SOLID, performance, or security.
- Rewrite code; output is advisory.
- Flag framework helpers (Django, DRF, django-filter) as duplicates of custom code — the custom one is the problem.
- Flag test helpers as duplicates of production code, or the reverse.
