# Branching, Commits & Pull Requests

Repo: `github.com/arbisoft/session-portal-backend`. CI (`.github/workflows/ci.yml`) runs on pushes to `main` and on every pull request. A container image is built and deployed when a GitHub release is published.

## Branches

- `main` is the integration branch and the default PR target. `origin/stage` currently sits at the same commit as `main`.
- Branch from an up-to-date `main`:

```bash
git fetch origin main
git checkout main && git pull --ff-only origin main
git checkout -b <username>/<topic-or-ticket>
```

- Naming: `<username>/<topic-or-ticket>` (for example `UY-test-branch`, or `arslan_allow_edly` from merged PR #72).
- Fix branches target the branch where the problem is present. If the fix must go to `stage` first, branch from `origin/stage` and PR into it; do not silently rebase it onto `main`.
- Do not branch from or push to `dependabot/*` branches.

## Commits

- Conventional style, scoped to the app: `feat(events): ...`, `fix(users): ...`, `refactor(events): ...`, `chore: ...`, `test(events): ...`.
- One logical change per commit; subject in the imperative, no trailing period.
- PR template asks to combine fix-up commits (`fix: lint issue`) into distinct sets of changes before merge.

## Pull Requests

Follow `.github/PULL_REQUEST_TEMPLATE.md`:

- Description of the change and a link to the Taiga ticket.
- At least two reviews before merge.
- Consider performance (query counts on list endpoints, ffmpeg on upload).
- Migrations must be backwards-compatible with the code currently deployed.
- `tox -e quality` and `pytest --cov` pass locally before opening the PR.
