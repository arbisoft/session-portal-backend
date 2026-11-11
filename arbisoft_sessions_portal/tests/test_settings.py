import importlib.util
import os
from pathlib import Path

import pytest

import arbisoft_sessions_portal.settings as settings_package


def local_settings_override(names):
    """ Return the names that settings/local.py defines, which base.py would otherwise let override its defaults """
    try:
        local_settings = importlib.import_module('arbisoft_sessions_portal.settings.local')
    except ImportError:
        return []
    return [name for name in names if hasattr(local_settings, name)]


def load_base_settings(monkeypatch):
    """ Evaluate settings/base.py in isolation, without the test overrides or a RESUMABLE_UPLOAD_ROOT env var """
    overridden = local_settings_override(('RESUMABLE_UPLOAD_ROOT', 'MEDIA_ROOT'))
    if overridden:
        pytest.skip(f'settings/local.py overrides {", ".join(overridden)}')
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    os.environ.pop('RESUMABLE_UPLOAD_ROOT', None)
    path = Path(settings_package.__file__).with_name('base.py')
    spec = importlib.util.spec_from_file_location('arbisoft_sessions_portal.settings.base_defaults', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if 'RESUMABLE_UPLOAD_ROOT' in os.environ:
        pytest.skip('RESUMABLE_UPLOAD_ROOT is set by the .env file')
    return module


def test_default_upload_root_is_outside_media(monkeypatch):
    """ Partial uploads must never be reachable through MEDIA_URL """
    base = load_base_settings(monkeypatch)
    upload_root = Path(base.RESUMABLE_UPLOAD_ROOT).resolve()
    media_root = Path(base.MEDIA_ROOT).resolve()

    assert not upload_root.is_relative_to(media_root)
    assert not media_root.is_relative_to(upload_root)
