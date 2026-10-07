import os
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import requests

from app import app as flask_app
from app.utils.session_tokens import SESSION_KEY, decrypt_canvas_token

BASE = "https://localhost"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    monkeypatch.setenv("CANVAS_API_CLIENT_ID", "client-id")
    monkeypatch.setenv("CANVAS_API_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("CANVAS_OAUTH_REDIRECT_URI", "https://tool.example.com/api/auth/callback")
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


class _TokenResponse:
    ok = True
    text = ""

    def json(self):
        return {"access_token": "canvas-token"}


@pytest.fixture
def token_exchange(monkeypatch):
    """Replace the Canvas token endpoint and record how often it is called."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _TokenResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    return calls


def _start_flow(client, course_id="42"):
    """Begin the OAuth flow as a browser would; return the `state` sent to Canvas."""
    res = client.get("/api/auth/canvas", query_string={"course_id": course_id}, base_url=BASE)
    assert res.status_code == 302
    query = urllib.parse.parse_qs(urllib.parse.urlparse(res.headers["Location"]).query)
    return query["state"][0]


def _callback(client, **params):
    return client.get("/api/auth/callback", query_string=params, base_url=BASE)


def _session(client):
    with client.session_transaction(base_url=BASE) as sess:
        return dict(sess)


# --- state generation --------------------------------------------------------

def test_state_is_an_unguessable_nonce_not_just_the_course_id(client):
    state = _start_flow(client, "42")
    nonce, _, course_id = state.partition(".")
    assert course_id == "42"
    assert len(nonce) >= 32
    assert nonce in _session(client)["oauth_states"]


def test_each_flow_gets_a_different_state(client):
    assert _start_flow(client) != _start_flow(client)


# --- callback verification ---------------------------------------------------

def test_callback_without_state_is_rejected_and_code_not_redeemed(client, token_exchange):
    res = _callback(client, code="abc")
    assert res.status_code == 400
    assert token_exchange == []
    assert "canvas_api_token" not in _session(client)


def test_login_csrf_forged_callback_is_rejected(client, token_exchange):
    """The attack: a victim's browser is sent to the callback with an attacker's
    authorization code, for a flow the victim's browser never started. It must
    not redeem the code or bind the attacker's token to the victim's session."""
    res = _callback(client, code="ATTACKER_CODE", state="attacker-chosen.42")
    assert res.status_code == 400
    assert token_exchange == []
    assert "canvas_api_token" not in _session(client)


def test_callback_with_wrong_nonce_is_rejected_even_mid_flow(client, token_exchange):
    _start_flow(client)  # the victim has a legitimate flow in progress
    res = _callback(client, code="abc", state="not-the-nonce.42")
    assert res.status_code == 400
    assert token_exchange == []


def test_callback_with_state_missing_separator_is_rejected(client, token_exchange):
    state = _start_flow(client)
    res = _callback(client, code="abc", state=state.split(".")[0])
    assert res.status_code == 400
    assert token_exchange == []


def test_valid_flow_completes_and_stores_token(client, token_exchange):
    state = _start_flow(client, "42")
    res = _callback(client, code="abc", state=state)

    assert res.status_code == 302
    assert res.headers["Location"] == "/launch_success?course_id=42"
    assert len(token_exchange) == 1
    sess = _session(client)
    # Stored encrypted, not as the raw bearer token.
    assert sess[SESSION_KEY] != "canvas-token"
    with flask_app.test_request_context():
        assert decrypt_canvas_token(sess[SESSION_KEY]) == "canvas-token"
    assert sess["canvas_course_id"] == "42"


def test_state_is_single_use(client, token_exchange):
    state = _start_flow(client)
    assert _callback(client, code="abc", state=state).status_code == 302
    replay = _callback(client, code="abc", state=state)
    assert replay.status_code == 400
    assert len(token_exchange) == 1


def test_two_concurrent_flows_can_both_complete(client, token_exchange):
    """Launching the tool twice (two tabs) must not invalidate the first flow."""
    first = _start_flow(client, "1")
    second = _start_flow(client, "2")
    assert _callback(client, code="a", state=first).status_code == 302
    assert _callback(client, code="b", state=second).status_code == 302


def test_oldest_pending_flow_is_eventually_dropped(client, token_exchange):
    states = [_start_flow(client, str(i)) for i in range(8)]
    assert len(_session(client)["oauth_states"]) <= 5
    assert _callback(client, code="a", state=states[0]).status_code == 400
    assert _callback(client, code="a", state=states[-1]).status_code == 302


def test_course_id_is_url_encoded_in_redirect(client, token_exchange):
    """A course id containing '&' must not inject extra query parameters."""
    state = _start_flow(client, "1&evil=1")
    res = _callback(client, code="abc", state=state)
    assert res.status_code == 302
    query = urllib.parse.parse_qs(urllib.parse.urlparse(res.headers["Location"]).query)
    assert query == {"course_id": ["1&evil=1"]}


def test_token_exchange_failure_does_not_store_token(client, monkeypatch):
    class _Bad:
        ok = False
        status_code = 400
        text = "invalid_grant"

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Bad())
    state = _start_flow(client)
    res = _callback(client, code="abc", state=state)
    assert res.status_code == 400
    assert "canvas_api_token" not in _session(client)


# --- upstream error bodies stay out of the browser ---------------------------

def _failing_exchange(monkeypatch, *, ok=False, text="invalid_grant: secret details", payload=None, json_error=False):
    class _Resp:
        def __init__(self):
            self.ok = ok
            self.status_code = 400
            self.text = text

        def json(self):
            if json_error:
                raise ValueError("not json")
            return payload

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())


@pytest.mark.parametrize("kwargs", [
    {"ok": False, "text": "invalid_grant: secret details"},
    {"ok": True, "text": "<html>gateway error: secret details</html>", "json_error": True},
    {"ok": True, "text": "secret details", "payload": {"error": "secret details"}},
    {"ok": True, "text": "secret details", "payload": ["not", "a", "dict"]},
])
def test_failed_token_exchange_shows_a_generic_message(client, monkeypatch, kwargs):
    """Regression: Canvas' raw error body (and parsed JSON) was echoed to the browser."""
    _failing_exchange(monkeypatch, **kwargs)
    state = _start_flow(client)
    res = _callback(client, code="abc", state=state)

    assert res.status_code == 400
    body = res.get_data(as_text=True)
    assert "secret details" not in body and "invalid_grant" not in body
    assert "relaunch" in body
    assert "canvas_api_token" not in _session(client)


def test_unreachable_canvas_during_token_exchange_is_a_clean_502(client, monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("dns failure for canvas.internal.example")

    monkeypatch.setattr(requests, "post", boom)
    state = _start_flow(client)
    res = _callback(client, code="abc", state=state)

    assert res.status_code == 502
    assert "dns failure" not in res.get_data(as_text=True)
