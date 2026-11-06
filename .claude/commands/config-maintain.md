---
description: Audit and update the Claude Code config (agents, skills, rules, CLAUDE.md) against the current code and pinned dependencies using config-maintainer-agent.
argument-hint: "[quick | full | audit] [focus, e.g. 'celery' or 'rules']"
---

# /config-maintain — Config Maintenance

Mode comes from `$ARGUMENTS`; the default is `quick`. Anything after the mode is a focus area that narrows the audit.

- **quick** (default) — run the audit script, then check the current diff against the config it can invalidate. No web research.
- **full** — quick plus research in official docs for the pinned versions; use after a dependency upgrade or about monthly.
- **audit** — read-only: report drift, change nothing.

## Workflow

1. Print the resolved mode and focus in one line.
2. Dispatch `config-maintainer-agent` with the mode, the focus, and the diff source (`git diff origin/main...HEAD` and uncommitted changes).
3. Output its report. Proposals (guardrail changes, deletions, tool or hook changes) are listed for the user to approve; do not apply them.
4. Do not stage or commit.

## References

- Procedure: `.claude/skills/config-maintenance/SKILL.md`
- Deterministic check: `python3 .claude/scripts/audit_config.py`
