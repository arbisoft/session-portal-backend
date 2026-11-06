---
name: config-maintenance
description: Methodology for auditing and updating the Sessions Portal backend's Claude Code configuration (agents, commands, skills, rules, CLAUDE.md, settings, hooks) so it stays accurate, non-duplicated, and current with the code and pinned dependencies. Used by config-maintainer-agent after a feature or review, or on demand. Runs the deterministic audit script first, researches official docs only when needed, and applies the smallest edit that removes the drift.
---

# Config Maintenance

Claude config is code: it rots when the code, tooling, or the tools that read it change. Keep it healthy with a **cheap deterministic check first, judgement second, research last**.

## Modes

| Mode | When | Web research | Output |
|------|------|--------------|--------|
| `quick` | End of a feature, fix, or review (default) | No | Audit + targeted edits driven by the diff |
| `full` | Explicit request, dependency upgrade, or roughly monthly | Yes, official sources | Audit + research + edits + recommendations |
| `audit` | Read-only check, or reviewing someone else's PR | No | Findings only; **no edits** (skip the "fix" and "re-run" parts of Steps 1 and 4, and list what you would change under `Gaps`) |

## Step 1 — Run the audit script

```bash
python3 .claude/scripts/audit_config.py
```

It checks frontmatter, path/skill/agent/symbol references, version and lint-limit claims, tox envs and `manage.py` commands, rule `paths:` globs, the rules index, undocumented modules, near-duplicate instructions, and CLAUDE.md size. Fix every ERROR. Triage each WARN: fix it, or add a reviewed third-party name to the script's external-names allowlist, or mark an intentional repeat with `<!-- audit:keep -->`. Re-run until it reports `clean` or only accepted warnings.

The script only proves facts. It cannot tell you a rule is wrong, missing, or contradicted by newer practice; Steps 2–4 do that.

## Step 2 — Map the change to the config it can invalidate

Read the diff (`git diff origin/main...HEAD` plus uncommitted, or the scope you were given) and use this table. Config files in that same uncommitted diff are the current state to audit against, not something to skip.

| The change... | Check and update |
|---|---|
| adds, renames, or removes a module, view, task, or management command | `CLAUDE.md` architecture, `rules/backend-django.md` layout, skill file references |
| bumps a pin in `requirements/*.txt`, `Dockerfile`, or CI | Version claims; run Step 5 (research) for the package |
| edits `tox.ini`, `pylintrc`, `.coveragerc`, `pytest.ini`, or workflows | `rules/backend-python.md`, `rules/testing.md`, `skills/python-linting` |
| edits `settings/*` or env vars | `CLAUDE.md` settings notes, `skills/django-backend-standards` Settings, README (hand to `documentation-generator`) |
| changes a model or migration | `DATABASE_DESIGN.md` (hand to `documentation-generator`), `skills/django-migration-standards` if the practice changed |
| introduces a pattern used at 2+ sites that no rule mentions | Add a rule bullet citing the precedent `file:function` |
| contradicts an existing rule (code is right, rule is stale) | Fix the rule; if the code is wrong, report it, do not edit the rule to match |
| triggered a recurring review finding (same finding in 2+ reviews) | Strengthen the rule or checklist item that should have prevented it |

## Step 3 — Single source of truth

Every fact has one owner. Others link to it; they do not restate it.

| Fact | Owner | Others |
|---|---|---|
| Lint limits, line length | `pylintrc`, `tox.ini` | `rules/backend-python.md` summarises; skills link |
| Library and Python versions | `requirements/*.txt`, `Dockerfile` | Docs name major.minor only |
| Coding standards | `.claude/rules/` | Skills and agents link |
| Procedures and checklists | `.claude/skills/` | Agents link |
| Role, tools, model | `.claude/agents/` | Nothing else |
| Commands to run | `CLAUDE.md`, `tox.ini` | Link or reuse verbatim |
| Always-on guardrails (confirm-before-changing list) | `CLAUDE.md` Conventions | `rules/security.md` links |
| Security and HTTP-response requirements | `rules/security.md` | Skills and checklists link |

On finding a duplicate, delete the copy that is not the owner and leave a pointer. Never fix drift by adding a third copy.

## Step 4 — Apply

- Smallest edit that removes the drift. Do not rewrite for style.
- Always-loaded files (`CLAUDE.md`): follow `.claude/skills/claude-md-writing/SKILL.md`; adding a line means the file stays under budget, so remove or move something.
- New or reworked rules get `paths:` frontmatter limiting them to the files they govern, unless they apply to every task. Rules load on matching reads, edits and writes, not every session.
- New skills and agents: frontmatter per the formats in Step 5; add the name to the audit by creating the file (it is discovered automatically); add a rule file to `.claude/rules/README.md`.
- Re-run the audit script after every batch of edits.

## Step 5 — Research (full mode, or a dependency bump)

Official sources only. Use blogs to find leads, then confirm in the official page.

| Topic | Source |
|---|---|
| Agent, skill, rule, hook, settings formats | `code.claude.com/docs` (sub-agents, skills, memory, hooks, settings) |
| Django | `docs.djangoproject.com` release notes for the pinned minor, and the deprecation timeline |
| DRF, drf-spectacular, simplejwt, django-filter | their release notes or changelogs on the project site or GitHub |
| Celery | `docs.celeryq.dev` (userguide: tasks, configuration, optimizing) |
| pylint, isort, pycodestyle, pytest-django | their changelogs |

Take each candidate recommendation through four gates; adopt only if it passes all:

1. **Applies** to the pinned version (`requirements/base.txt`, `dev.txt`), not only a newer one.
2. **Grounded** in this codebase: a precedent, a conflict, or a bug it prevents (cite `file:line`).
3. **New**: not already covered by a rule or skill.
4. **Compatible** with `CLAUDE.md` conventions (for example: no default `services.py`, `asp_api` logger, thin views).

Advice for a newer major (for example moving to the next Django release) goes into the report as a recommendation. It does not become a standing rule until the repo pins that version.

## Guardrails

Config can weaken itself, so these need the user's explicit approval and are reported as proposals, never applied:

- Adding to, removing, or loosening anything in `rules/security.md`, `rules/branching.md`, the `CLAUDE.md` confirm-before-changing list, or an agent's "Hard rules".
- Changing which tools or model an agent runs with, or adding hooks or permissions.
- Editing `.claude/scripts/audit_config.py` logic (its allowlists and thresholds may be updated).
- Deleting a rule, skill, agent, or command.

Also: do not edit application code (report code that contradicts a rule), do not stage or commit, and do not touch `README.md` or `DATABASE_DESIGN.md` directly (hand to `documentation-generator`).

## Report

```
## Config Maintenance (<mode>)
Audit      : <n errors, n warnings before> -> <after>
Changed    : <file — one-line reason>, ...
Removed dup: <file:line -> kept in file>, ...
Researched : <topic — source URL, date read>   (full mode only)
Gaps       : <audit mode, or not applied: gap found, proposed bullet and target file>
Proposals  : <needs your approval: change, why>
Code vs rule conflicts : <file:line — rule it contradicts>
No change  : <considered and rejected, one line each>
```

If nothing needed changing: `Config is current — audit clean, no drift from this diff.`
