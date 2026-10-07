import json
import os
import stat
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from flask import Flask

from app.utils import lti_utils

KEY = "-----BEGIN PRIVATE KEY-----\nTOPSECRET\n-----END PRIVATE KEY-----"


@pytest.fixture
def lti_app(tmp_path, monkeypatch):
    """A throwaway app whose root has a config/config.json but no private.key on disk."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({
        "http://canvas.docker:8081": [{
            "client_id": "123",
            "auth_login_url": "http://canvas.docker:8081/api/lti/authorize_redirect",
            "auth_token_url": "http://canvas.docker:8081/login/oauth2/token",
            "key_set_url": "http://canvas.docker:8081/api/lti/security/jwks",
            "private_key_file": "private.key",
            "public_key_file": "public.key",
            "deployment_ids": ["1:abc"],
        }]
    }))
    monkeypatch.setenv("LTI_PRIVATE_KEY", KEY)
    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    lti_utils._ephemeral.update(signature=None, config_path=None)
    return Flask("lti_test", root_path=str(tmp_path))


def _entry(config_path):
    with open(config_path) as f:
        return next(iter(json.load(f).values()))[0]


def test_key_and_config_are_written_privately(lti_app):
    with lti_app.app_context():
        path = lti_utils.get_lti_config_path()

    entry = _entry(path)
    key_path = entry["private_key_file"]
    assert open(key_path).read() == KEY

    # Owner-only files inside an owner-only, unpredictably named directory.
    assert stat.S_IMODE(os.stat(key_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    key_dir = os.path.dirname(key_path)
    assert stat.S_IMODE(os.stat(key_dir).st_mode) == 0o700
    assert os.path.dirname(path) == key_dir
    # Not dropped loose in the shared temp dir at a predictable name.
    assert key_dir != tempfile.gettempdir()
    assert os.path.basename(key_dir).startswith("lti-config-")


def test_hostnames_are_rewired_to_canvas_domain(lti_app):
    with lti_app.app_context():
        entry = _entry(lti_utils.get_lti_config_path())
    assert entry["auth_login_url"] == "https://canvas.example.com/api/lti/authorize_redirect"
    assert entry["key_set_url"] == "https://canvas.example.com/api/lti/security/jwks"


def test_files_are_not_rewritten_on_every_call(lti_app):
    """Regression: the key used to be rewritten on every request."""
    with lti_app.app_context():
        first = lti_utils.get_lti_config_path()
        key_path = _entry(first)["private_key_file"]
        before = os.stat(key_path)
        second = lti_utils.get_lti_config_path()
        after = os.stat(key_path)

    assert first == second
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_concurrent_requests_never_see_a_truncated_key(lti_app):
    """Regression: concurrent requests rewrote the same shared file, so a reader
    could observe it half-written."""
    results, errors = [], []

    def worker():
        try:
            with lti_app.app_context():
                for _ in range(25):
                    path = lti_utils.get_lti_config_path()
                    results.append(path)
                    assert open(_entry(path)["private_key_file"]).read() == KEY
        except Exception as e:  # noqa: BLE001 - surface any failure from the thread
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(set(results)) == 1


def test_changed_key_is_picked_up(lti_app, monkeypatch):
    with lti_app.app_context():
        first = lti_utils.get_lti_config_path()
        monkeypatch.setenv("LTI_PRIVATE_KEY", "A-DIFFERENT-KEY")
        second = lti_utils.get_lti_config_path()

    assert first != second
    assert open(_entry(second)["private_key_file"]).read() == "A-DIFFERENT-KEY"


def test_key_file_on_disk_takes_precedence(lti_app, tmp_path):
    (tmp_path / "config" / "private.key").write_text("on-disk-key")
    with lti_app.app_context():
        assert lti_utils.get_lti_config_path() == str(tmp_path / "config" / "config.json")


def test_without_env_key_the_plain_config_is_used(lti_app, tmp_path, monkeypatch):
    monkeypatch.delenv("LTI_PRIVATE_KEY")
    with lti_app.app_context():
        assert lti_utils.get_lti_config_path() == str(tmp_path / "config" / "config.json")
