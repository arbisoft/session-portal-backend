---
description: Review local changes, the current branch, or a pull request in the Sessions Portal backend using the portal-code-review skill, then auto-fix the findings.
argument-hint: "[staged | <branch> | main | stage | <PR number> | blank for uncommitted changes] [--review-only]"
---

# /portal-review — Backend Code Review

Scope comes from `$ARGUMENTS` (`--review-only` is a mode flag, not part of the scope):

- **blank** → uncommitted changes (`git diff` + `git diff --staged`)
- **`staged`** → `git diff --staged`
- **`main`** / **`stage`** → `git diff origin/<name>...HEAD`
- **a branch name** → `git diff origin/main...<branch>`
- **a number** → GitHub PR: `gh pr diff <number>` for the diff and `gh pr view <number>` for title and description (review only unless that branch is checked out)

## Workflow

1. Resolve scope and print it in one line.
2. Invoke the `portal-code-review` skill with that diff.
3. Output the skill's review. Do not post it to GitHub unless the user asks.
4. Unless `--review-only` was passed, let the skill fix the findings (its Steps 7–8) and output its fix report. Do not stage or commit the fixes.

## Rules

- Silence means pass. A clean diff is one line.
- Do not invent rules outside `.claude/rules/`.

## References

- Skill: `.claude/skills/portal-code-review/SKILL.md`
- Standards: `.claude/rules/`
- PR template: `.github/PULL_REQUEST_TEMPLATE.md`
