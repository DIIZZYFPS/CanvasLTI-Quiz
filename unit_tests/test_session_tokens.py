import base64
import json
import os
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import requests
from flask import Flask

from app import app as flask_app, create_app
from app.utils.session_tokens import (
    SESSION_KEY,
    clear_canvas_token,
    decrypt_canvas_token,
    encrypt_canvas_token,
    get_canvas_token,
    has_canvas_token,
    store_canvas_token,
)

BASE = "https://localhost"
TOKEN = "SECRET_CANVAS_TOKEN_123"


# --- the token store ---------------------------------------------------------

def test_round_trip_and_ciphertext_hides_token():
    with flask_app.test_request_context():
        store_canvas_token(TOKEN)
        from flask import session
        assert TOKEN not in session[SESSION_KEY]
        assert get_canvas_token() == TOKEN
        assert has_canvas_token()


def test_each_encryption_is_distinct():
    with flask_app.test_request_context():
        assert encrypt_canvas_token(TOKEN) != encrypt_canvas_token(TOKEN)


def test_missing_token():
    with flask_app.test_request_context():
        assert get_canvas_token() is None
        assert not has_canvas_token()


def test_clear():
    with flask_app.test_request_context():
        store_canvas_token(TOKEN)
        clear_canvas_token()
        assert get_canvas_token() is None


def test_value_encrypted_under_a_different_secret_is_rejected_and_dropped():
    """Rotating SECRET_KEY must force re-authorisation, not decrypt old tokens."""
    other = Flask("other")
    other.secret_key = "a-completely-different-secret-key"
    with other.app_context():
        foreign = encrypt_canvas_token(TOKEN)

    with flask_app.test_request_context():
        from flask import session
        assert decrypt_canvas_token(foreign) is None
        session[SESSION_KEY] = foreign
        assert get_canvas_token() is None
        assert SESSION_KEY not in session


def test_legacy_plaintext_token_is_not_accepted():
    """Cookies issued before encryption existed hold the raw token; those users
    must simply re-authorise rather than be treated as logged in."""
    with flask_app.test_request_context():
        from flask import session
        session[SESSION_KEY] = TOKEN
        assert get_canvas_token() is None
        assert SESSION_KEY not in session


@pytest.mark.parametrize("junk", [None, "", 123, ["x"], "not-a-fernet-token", "gAAAAAB" + "x" * 40])
def test_garbage_is_rejected(junk):
    with flask_app.test_request_context():
        assert decrypt_canvas_token(junk) is None


def test_tampered_ciphertext_is_rejected():
    with flask_app.test_request_context():
        blob = encrypt_canvas_token(TOKEN)
        flipped = blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB")
        assert decrypt_canvas_token(flipped) is None


# --- what actually reaches the browser ---------------------------------------

def test_token_is_not_readable_in_the_session_cookie(monkeypatch):
    """Regression: the cookie is signed but not encrypted, so the raw Canvas
    token used to be readable by anyone holding it."""
    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    monkeypatch.setenv("CANVAS_API_CLIENT_ID", "id")
    monkeypatch.setenv("CANVAS_API_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CANVAS_OAUTH_REDIRECT_URI", "https://tool.example.com/api/auth/callback")

    class _Resp:
        ok = True
        text = ""
        def json(self): return {"access_token": TOKEN}

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())

    client = flask_app.test_client()
    import urllib.parse
    res = client.get("/api/auth/canvas", query_string={"course_id": "42"}, base_url=BASE)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(res.headers["Location"]).query)["state"][0]
    res = client.get("/api/auth/callback", query_string={"code": "c", "state": state}, base_url=BASE)
    assert res.status_code == 302

    raw = client.get_cookie("pylti1p3-flask-app-sessionid").value
    # itsdangerous format: [.]payload.timestamp.signature ('.'-prefixed when zlib-compressed)
    compressed = raw.startswith(".")
    payload = raw.lstrip(".").split(".")[0]
    decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    if compressed:
        decoded = zlib.decompress(decoded)
    data = json.loads(decoded)

    assert TOKEN not in raw and TOKEN not in decoded.decode()
    assert SESSION_KEY in data  # still there, just opaque


# --- SECRET_KEY --------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "", "replace-me-in-production", "your_secure_random_flask_secret"])
def test_missing_or_placeholder_secret_key_gets_random_key_and_warns(monkeypatch, value):
    """Regression: an unset SECRET_KEY used to fall back to a *public* default,
    so anyone could forge a session. The key must never be a known value."""
    if value is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", value)

    with pytest.warns(RuntimeWarning, match="SECRET_KEY"):
        a = create_app()
    with pytest.warns(RuntimeWarning):
        b = create_app()

    assert a.secret_key not in {"replace-me-in-production", "your_secure_random_flask_secret", ""}
    assert len(a.secret_key) >= 32
    assert a.secret_key != b.secret_key


def test_configured_secret_key_is_used_without_warning(monkeypatch, recwarn):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    app = create_app()
    assert app.secret_key == "x" * 40
    assert not [w for w in recwarn if "SECRET_KEY" in str(w.message)]


def test_session_backend_config_that_nothing_implemented_is_gone():
    """SESSION_TYPE/SESSION_FILE_DIR implied server-side sessions, but Flask-Session
    was never installed, so they were dead config that misled operators."""
    assert "SESSION_TYPE" not in flask_app.config
    assert "SESSION_FILE_DIR" not in flask_app.config
