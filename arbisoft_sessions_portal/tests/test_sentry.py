import importlib
from unittest.mock import patch

import arbisoft_sessions_portal
from arbisoft_sessions_portal.sentry import init_sentry


def test_init_sentry_skipped_without_dsn(settings):
    """ No Sentry client is created when SENTRY_DSN is None """
    settings.SENTRY_DSN = None
    with patch("arbisoft_sessions_portal.sentry.sentry_sdk.init") as mock_init:
        init_sentry()
    mock_init.assert_not_called()


def test_init_sentry_uses_settings_values(settings):
    """ The Sentry client is configured from the final settings values """
    settings.SENTRY_DSN = "https://key@example.invalid/1"
    settings.SENTRY_ENVIRONMENT = "production"
    settings.SENTRY_TRACES_SAMPLE_RATE = 0.25
    settings.SENTRY_PROFILE_SESSION_SAMPLE_RATE = 0.5
    with patch("arbisoft_sessions_portal.sentry.sentry_sdk.init") as mock_init:
        init_sentry()
    mock_init.assert_called_once_with(
        dsn="https://key@example.invalid/1",
        environment="production",
        traces_sample_rate=0.25,
        profile_session_sample_rate=0.5,
        profile_lifecycle="trace",
    )


def test_package_import_initialises_sentry():
    """ Importing the project package, which every process does first, initialises Sentry """
    with patch("arbisoft_sessions_portal.sentry.init_sentry") as mock_init:
        importlib.reload(arbisoft_sessions_portal)
    mock_init.assert_called_once_with()
