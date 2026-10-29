# SOLID Principles

Applied to this Django + DRF codebase.

## S — Single Responsibility

- One reason to change per class or function.
- Views handle request flow; serializers handle shape and validation; `utils.py` holds shared logic.
- If a function validates, persists, notifies, AND formats — split it.

## O — Open / Closed

- Open for extension, closed for modification.
- Prefer strategy maps, mixins, and decorators over growing if/elif chains.

```python
# BAD
if user_type == "premium": ...
elif user_type == "vip": ...

# GOOD
STRATEGIES = {"premium": ..., "vip": ...}
strategy = STRATEGIES.get(user_type, default)
```

## L — Liskov Substitution

- Subclass methods honor the parent contract (same params, compatible returns).
- Overriding `save()` / `clean()` / `delete()` must call `super()` unless explicitly documented otherwise (`VideoAsset.save()` is the example to follow).

## I — Interface Segregation

- Serializers include only the fields relevant to the endpoint (list vs detail vs create).
- API payloads stay lean.

## D — Dependency Inversion

- External systems (Google OAuth, Google Drive, ffmpeg) are reached through `arbisoft_sessions_portal/services/` or a model/util helper — do not scatter raw `requests` calls through views.
- Extract reusable ORM logic to utils, model methods, or custom querysets.
- Config values (URLs, flags, allowed domains) come from settings/env, not hardcoded.
