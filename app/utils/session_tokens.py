"""Encrypted storage for the Canvas API token inside the Flask session.

Flask's default session is a *client-side* cookie: it is signed, so it can't be
forged, but it is not encrypted, so anyone holding the cookie (a proxy log, a
browser extension, a leaked HAR file) can read the Canvas bearer token out of
it. Server-side sessions would avoid that, but they add a dependency
(Flask-Session) and a directory of session files that must be secured, cleaned
up, and shared between gunicorn workers. Encrypting just the token keeps the
sessions stateless and keeps the secret unreadable to anyone who obtains the
cookie, without any of that. (To move to server-side sessions later, only the
storage in this module needs to change.)

The encryption key is derived from SECRET_KEY, so rotating SECRET_KEY simply
invalidates stored tokens and users re-authorise.
"""
import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import current_app, session

SESSION_KEY = 'canvas_api_token'


def _fernet():
    secret = current_app.secret_key
    if isinstance(secret, str):
        secret = secret.encode()
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"canvas-quiz:session-token:v1",
    ).derive(secret)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_canvas_token(token):
    return _fernet().encrypt(token.encode()).decode()


def decrypt_canvas_token(blob):
    """Return the token, or None if `blob` isn't a token encrypted with the current key."""
    if not isinstance(blob, str) or not blob:
        return None
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except InvalidToken:
        # Wrong/rotated SECRET_KEY, a tampered value, or a plaintext token left in
        # a cookie issued before encryption existed: treat as "not authorised".
        return None


def store_canvas_token(token):
    session[SESSION_KEY] = encrypt_canvas_token(token)


def get_canvas_token():
    """The decrypted Canvas token for this session, or None. Drops an unusable value."""
    blob = session.get(SESSION_KEY)
    if blob is None:
        return None
    token = decrypt_canvas_token(blob)
    if token is None:
        session.pop(SESSION_KEY, None)
    return token


def has_canvas_token():
    return get_canvas_token() is not None


def clear_canvas_token():
    session.pop(SESSION_KEY, None)
