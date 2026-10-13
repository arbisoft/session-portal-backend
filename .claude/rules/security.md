# Security Rules

## Secrets

- No hardcoded API keys, tokens, passwords, DB URLs, or OAuth credentials in source.
- Configuration comes from environment variables (`.env` via python-dotenv) or the gitignored `settings/local.py`. `.env` and `local.py` are never committed.

## Input Validation

- Validate all user input through DRF serializers or `django_filters` — do not trust raw `request.data` or `request.query_params`.
- No raw SQL with string interpolation. Use the ORM or parameterized queries; no unvalidated user input reaching `.extra()` or `.raw()`.
- Uploads: `VideoAsset.video_file` is extension-validated; any new upload field needs its own validator and a size/type consideration, because `VideoAsset.save()` hands the file to ffmpeg.
- Google Drive links accepted by the admin import (`events.tasks.download_google_drive_video`) are user-supplied URLs — keep the download scoped to Drive and never pass user input to a shell.

## Authentication & Permissions

- Auth is JWT (simplejwt) plus session auth, and `IsAuthenticated` is the global default. A new view must not weaken this; `permission_classes = []` is for login views only.
- Staff-only endpoints use `IsStaffPermission` from `users/permissions.py` — no ad-hoc `request.user.is_staff` checks in view bodies.
- Google login must keep rejecting accounts whose `hd` is outside `arbisoft.com` / `edly.io` while `ALLOW_ONLY_INTERNAL_USERS` is true.
- Login responses expose `is_staff` for the client only; never trust a client-supplied role.

## API Responses

- Never expose passwords, tokens, or internal-only IDs in responses.
- Error messages must not leak stack traces, file paths, or ffmpeg output to clients.
- `UserSearchView` is staff-only because it lists users — keep the output minimal (no password hashes, permissions, last-login details).

## High-Scrutiny Surfaces

Pause and confirm with the user before changing: `users/v1/views.py` login flows, `GoogleUserInfoService`, `users/permissions.py`, JWT/CORS/`ALLOWED_HOSTS`/`ALLOW_ONLY_INTERNAL_USERS` settings, and anything that changes who can reach an endpoint.
