"""LTI 1.3 login and launch, end to end, against the real pylti1p3 validation.

A throwaway "Canvas" is simulated by a key pair whose public half is published inline in the
tool config (`key_set`), so the tool verifies real RS256 id_tokens without any network.
"""
import json
import os
import sys
import time
import urllib.parse
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from jwt.algorithms import RSAAlgorithm

from app import app as flask_app
from app.config import keys
from app.utils.session_tokens import SESSION_KEY, encrypt_canvas_token

BASE = "https://tool.test"
ISSUER = "https://canvas.test"
CLIENT_ID = "client-1"
DEPLOYMENT_ID = "dep-1"
KID = "platform-key-1"
LTI = "https://purl.imsglobal.org/spec/lti/claim/"


@pytest.fixture
def platform(tmp_path, monkeypatch):
    """A fake Canvas (its signing key) plus a tool config that trusts it."""
    platform_private, platform_public = keys.generate_key_pair(2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(serialization.load_pem_public_key(platform_public)))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})

    tool_private, tool_public = keys.generate_key_pair(2048)
    private_path, public_path = keys.write_key_pair(str(tmp_path), tool_private, tool_public)

    config = tmp_path / "config.json"
    config.write_text(json.dumps({ISSUER: [{
        "client_id": CLIENT_ID,
        "auth_login_url": ISSUER + "/api/lti/authorize_redirect",
        "auth_token_url": ISSUER + "/login/oauth2/token",
        "key_set_url": ISSUER + "/api/lti/security/jwks",
        "key_set": {"keys": [jwk]},
        "private_key_file": private_path,
        "public_key_file": public_path,
        "deployment_ids": [DEPLOYMENT_ID],
    }]}))
    monkeypatch.setattr("app.routes.lti.get_lti_config_path", lambda: str(config))

    return SimpleNamespace(client=flask_app.test_client(), signing_key=platform_private, tool_public=tool_public)


def _login(platform, **params):
    query = {
        "iss": ISSUER, "client_id": CLIENT_ID, "login_hint": "user-1",
        "target_link_uri": BASE + "/launch/", "lti_message_hint": "hint-1",
    }
    query.update(params)
    return platform.client.get("/login/", query_string={k: v for k, v in query.items() if v is not None}, base_url=BASE)


def _redirect_params(response):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(response.headers["Location"]).query).items()}


def _id_token(platform, nonce, signing_key=None, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": CLIENT_ID, "sub": "user-1", "iat": now, "exp": now + 300, "nonce": nonce,
        LTI + "message_type": "LtiResourceLinkRequest",
        LTI + "version": "1.3.0",
        LTI + "deployment_id": DEPLOYMENT_ID,
        LTI + "target_link_uri": BASE + "/launch/",
        LTI + "resource_link": {"id": "rl-1"},
        LTI + "roles": ["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
        LTI + "context": {"id": "6d1c2e5a-context-uuid", "label": "BIO101"},
        LTI + "custom": {"canvas_course_id": "4242"},
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key or platform.signing_key, algorithm="RS256", headers={"kid": KID})


def _full_launch(platform, **overrides):
    """Do the login redirect, then launch with a token for the nonce it issued."""
    login = _login(platform)
    assert login.status_code == 302, login.get_data(as_text=True)
    params = _redirect_params(login)
    token = _id_token(platform, params["nonce"], **overrides)
    return platform.client.post("/launch/", data={"state": params["state"], "id_token": token}, base_url=BASE)


def _session(platform):
    with platform.client.session_transaction(base_url=BASE) as sess:
        return dict(sess)


# --- OIDC login ---------------------------------------------------------------

def test_login_redirects_to_the_platform_with_state_and_nonce(platform):
    response = _login(platform)
    assert response.status_code == 302
    assert response.headers["Location"].startswith(ISSUER + "/api/lti/authorize_redirect?")
    params = _redirect_params(response)
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == BASE + "/launch/"
    assert params["login_hint"] == "user-1"
    assert params["response_type"] == "id_token" and params["response_mode"] == "form_post"
    assert len(params["state"]) >= 16 and len(params["nonce"]) >= 16


def test_login_accepts_post_as_canvas_may_send_it(platform):
    response = platform.client.post("/login/", data={
        "iss": ISSUER, "client_id": CLIENT_ID, "login_hint": "u", "target_link_uri": BASE + "/launch/",
    }, base_url=BASE)
    assert response.status_code == 302


def test_each_login_gets_a_fresh_state_and_nonce(platform):
    first, second = _redirect_params(_login(platform)), _redirect_params(_login(platform))
    assert first["state"] != second["state"] and first["nonce"] != second["nonce"]


@pytest.mark.parametrize("overrides", [
    {"iss": "https://evil.test"},        # an issuer the tool is not registered with
    {"iss": None},                       # missing parameters
    {"login_hint": None},
    {"client_id": "someone-elses-client"},
])
def test_login_that_cannot_be_matched_to_a_registration_is_a_clean_400(platform, overrides):
    """Regression: these were unhandled exceptions, i.e. a 500 with a stack trace for anyone who
    could reach the endpoint."""
    response = _login(platform, **overrides)
    assert response.status_code == 400
    assert "relaunch" in response.get_data(as_text=True).lower()
    assert "Traceback" not in response.get_data(as_text=True)


# --- launch: the happy path ---------------------------------------------------

def test_launch_without_a_canvas_token_starts_the_api_authorisation(platform):
    response = _full_launch(platform)
    assert response.status_code == 302
    assert response.headers["Location"] == "/api/auth/canvas?course_id=4242"
    assert _session(platform)["canvas_course_id"] == "4242"


def test_launch_with_an_existing_canvas_token_goes_straight_to_the_app(platform):
    with flask_app.app_context():
        blob = encrypt_canvas_token("tok")
    with platform.client.session_transaction(base_url=BASE) as sess:
        sess[SESSION_KEY] = blob
    response = _full_launch(platform)
    assert response.status_code == 302
    assert response.headers["Location"] == "/launch_success?course_id=4242"


def test_course_id_falls_back_through_the_documented_custom_keys(platform):
    for key in ("course_id", "custom_canvas_course_id", "custom_course_id"):
        platform.client = flask_app.test_client()
        response = _full_launch(platform, **{LTI + "custom": {key: "77"}})
        assert response.headers["Location"] == "/api/auth/canvas?course_id=77", key


def test_course_id_falls_back_to_the_context_claim_but_the_app_then_says_it_cannot_use_it(platform):
    """With no custom field the context id is used. It is Canvas' opaque id, not the numeric course
    id the API needs, so /api/session reports no usable course (the UI shows 'course not detected')."""
    response = _full_launch(platform, **{LTI + "custom": {}})
    assert _session(platform)["canvas_course_id"] == "6d1c2e5a-context-uuid"
    assert platform.client.get("/api/session", base_url=BASE).get_json()["canvas"]["course_id"] is None
    assert "course_id=6d1c2e5a-context-uuid" in response.headers["Location"]


def test_course_id_with_special_characters_cannot_inject_query_parameters(platform):
    response = _full_launch(platform, **{LTI + "custom": {"canvas_course_id": "1&admin=true"}})
    query = urllib.parse.parse_qs(urllib.parse.urlparse(response.headers["Location"]).query)
    assert query == {"course_id": ["1&admin=true"]}


# --- launch: everything that must be refused ----------------------------------

def _assert_refused(response):
    assert response.status_code == 400, response.get_data(as_text=True)
    assert "relaunch" in response.get_data(as_text=True).lower()
    assert "Traceback" not in response.get_data(as_text=True)


def test_launch_with_a_forged_signature_is_refused(platform):
    other_key, _ = keys.generate_key_pair(2048)
    _assert_refused(_full_launch(platform, signing_key=other_key))


def test_reposting_a_launch_from_the_same_browser_is_allowed_but_not_from_another(platform):
    """pylti1p3 does not consume nonces, so refreshing the POSTed launch page works (the redirect
    in launch() exists so a refresh lands on a GET). What stops a captured token being reused is
    the state, which only validates in the browser that started the login, and the token's `exp`."""
    params = _redirect_params(_login(platform))
    data = {"state": params["state"], "id_token": _id_token(platform, params["nonce"])}
    assert platform.client.post("/launch/", data=data, base_url=BASE).status_code == 302
    assert platform.client.post("/launch/", data=data, base_url=BASE).status_code == 302
    _assert_refused(flask_app.test_client().post("/launch/", data=data, base_url=BASE))


def test_launch_with_a_nonce_the_tool_never_issued_is_refused(platform):
    login = _login(platform)
    params = _redirect_params(login)
    token = _id_token(platform, "a-nonce-this-tool-never-issued")
    _assert_refused(platform.client.post("/launch/", data={"state": params["state"], "id_token": token}, base_url=BASE))


def test_launch_with_a_state_from_another_browser_is_refused(platform):
    """The state must match the cookie set at login: a token for someone else's login can't be
    submitted from a browser that didn't start it."""
    params = _redirect_params(_login(platform))
    token = _id_token(platform, params["nonce"])
    stranger = flask_app.test_client()
    _assert_refused(stranger.post("/launch/", data={"state": params["state"], "id_token": token}, base_url=BASE))


@pytest.mark.parametrize("data", [{}, {"state": "x"}, {"id_token": "x"}, {"state": "x", "id_token": "not-a-jwt"}])
def test_launch_with_missing_or_garbage_parameters_is_refused(platform, data):
    _assert_refused(platform.client.post("/launch/", data=data, base_url=BASE))


@pytest.mark.parametrize("name,overrides", [
    ("expired", {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}),
    ("wrong audience", {"aud": "another-client"}),
    ("wrong issuer", {"iss": "https://evil.test"}),
    ("unknown deployment", {LTI + "deployment_id": "not-a-registered-deployment"}),
])
def test_launch_with_invalid_claims_is_refused(platform, name, overrides):
    _assert_refused(_full_launch(platform, **overrides))


def test_launch_with_a_deep_linking_message_is_not_special_cased(platform):
    """The old code skipped nonce validation for the IMS reference platform's deep-link launches.
    That path is gone: a deep-link launch with a bad nonce is refused like any other."""
    params = _redirect_params(_login(platform))
    token = _id_token(platform, "bad-nonce", **{
        "iss": "http://imsglobal.org", LTI + "message_type": "LtiDeepLinkingRequest",
    })
    response = platform.client.post("/launch/", data={"state": params["state"], "id_token": token}, base_url=BASE)
    assert response.status_code == 400


def test_a_get_to_launch_does_not_start_a_launch(platform):
    """/launch/ only handles POSTs; a GET falls through to the app shell and creates no session."""
    platform.client.get("/launch/", base_url=BASE)
    assert "canvas_course_id" not in _session(platform)


# --- JWKS ---------------------------------------------------------------------

def test_jwks_publishes_only_the_tools_public_key(platform):
    response = platform.client.get("/jwks/", base_url=BASE)
    assert response.status_code == 200
    keyset = response.get_json()
    assert len(keyset["keys"]) == 1
    published = keyset["keys"][0]
    assert published["kty"] == "RSA"
    assert not {"d", "p", "q", "dp", "dq", "qi"} & set(published), "private key material must never be published"
    assert "kid" in published
