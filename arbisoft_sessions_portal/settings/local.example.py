import os
from dotenv import load_dotenv

load_dotenv()

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST"),
        "PORT": os.getenv("DB_PORT"),
    }
}

# Optional overrides. Each of these is also read from the environment (or .env) in base.py,
# so uncomment one here only if you want it fixed for this machine.

# Resumable uploads. The default keeps partial files outside MEDIA_ROOT; do not point this inside it.
# RESUMABLE_UPLOAD_ROOT = "/path/to/uploads_tmp"
# RESUMABLE_UPLOAD_MAX_FILE_BYTES = 20 * 1024 ** 3
# RESUMABLE_UPLOAD_CHUNK_BYTES = 8 * 1024 ** 2
# RESUMABLE_UPLOAD_MAX_CHUNK_BYTES = 16 * 1024 ** 2
# RESUMABLE_UPLOAD_SESSION_TTL_HOURS = 72
# RESUMABLE_UPLOAD_MAX_ACTIVE_PER_USER = 3
# RESUMABLE_UPLOAD_MIN_FREE_BYTES = 1024 ** 3
# RESUMABLE_UPLOAD_FINALIZE_STALE_MINUTES = 30
# RESUMABLE_UPLOAD_FINALIZE_TIMEOUT_HOURS = 6
# RESUMABLE_UPLOAD_RETENTION_DAYS = 7

# Sentry error reporting is off while SENTRY_DSN is unset.
# SENTRY_DSN = "https://<key>@<org>.ingest.sentry.io/<project>"
# SENTRY_ENVIRONMENT = "local"
# SENTRY_TRACES_SAMPLE_RATE = 0.0
# SENTRY_PROFILE_SESSION_SAMPLE_RATE = 0.0
