from flask import Blueprint, request, redirect, session, current_app
import hmac
import secrets
import requests
import urllib.parse
import os
from ..utils.render_utils import clean_course_id, render_app
from ..utils.session_tokens import store_canvas_token

auth_bp = Blueprint('auth', __name__)

# How many in-flight authorizations a browser session may have at once (e.g. the
# tool launched twice in two tabs). Older ones are dropped.
_MAX_PENDING_OAUTH_STATES = 5

def _new_oauth_state(course_id):
    """Create the OAuth `state` value and remember its nonce in this session.

    `state` used to be just the course id. OAuth requires it to be an
    unguessable value tied to the user's browser (RFC 6749 s10.12); without
    that, an attacker could start a flow with their own Canvas account and trick
    a victim into completing it (/api/auth/callback?code=<attacker code>), which
    silently signs the victim into the attacker's Canvas token so the victim's
    quizzes are imported into the attacker's course. The course id still rides
    along after the nonce so the round trip doesn't depend on other session data.
    """
    nonce = secrets.token_urlsafe(32)
    pending = list(session.get('oauth_states', []))[-(_MAX_PENDING_OAUTH_STATES - 1):]
    pending.append(nonce)
    session['oauth_states'] = pending
    return f"{nonce}.{course_id}"

def _consume_oauth_state(returned_state):
    """Validate the `state` Canvas sent back. Returns the course id, or None if invalid.

    A state is single-use: it is removed from the session once matched.
    """
    if not returned_state or '.' not in returned_state:
        return None
    nonce, _, course_id = returned_state.partition('.')
    pending = list(session.get('oauth_states', []))
    for known in pending:
        if hmac.compare_digest(known.encode(), nonce.encode()):
            pending.remove(known)
            session['oauth_states'] = pending
            return clean_course_id(course_id)
    return None

@auth_bp.route('/api/auth/canvas', methods=['GET'])
def auth_canvas():
    CANVAS_DOMAIN = os.getenv('CANVAS_DOMAIN')
    API_CLIENT_ID = os.getenv('CANVAS_API_CLIENT_ID')
    API_REDIRECT_URI = os.getenv('CANVAS_OAUTH_REDIRECT_URI')
    
    if not CANVAS_DOMAIN or not API_CLIENT_ID or not API_REDIRECT_URI:
        return (
            "Canvas OAuth is not configured. Please set CANVAS_DOMAIN, "
            "CANVAS_API_CLIENT_ID, and CANVAS_OAUTH_REDIRECT_URI environment variables."
        ), 500
    
    # Recover course_id from query parameters or session
    course_id = clean_course_id(request.args.get('course_id') or session.get('canvas_course_id', ''))

    # These are the REST scopes that the LTI Key cannot have
    scopes = [
        'url:POST|/api/v1/courses/:course_id/content_migrations',
        'url:GET|/api/v1/progress/:id',
        'url:POST|/api/v1/courses/:course_id/files'
    ]
    
    # Build the OAuth2 URL specifically using the API_CLIENT_ID
    params = {
        'client_id': API_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': API_REDIRECT_URI,
        'scope': ' '.join(scopes),
        'state': _new_oauth_state(course_id),
    }
    
    auth_url = f"{CANVAS_DOMAIN}/login/oauth2/auth?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)

@auth_bp.route('/api/auth/callback', methods=['GET'])
def auth_callback():
    CANVAS_DOMAIN = os.getenv('CANVAS_DOMAIN')
    API_CLIENT_ID = os.getenv('CANVAS_API_CLIENT_ID')
    API_CLIENT_SECRET = os.getenv('CANVAS_API_CLIENT_SECRET')
    API_REDIRECT_URI = os.getenv('CANVAS_OAUTH_REDIRECT_URI')

    code = request.args.get('code')

    if not code:
        return "Missing authorization code", 400

    # Verify `state` BEFORE exchanging the code: never redeem a code for a request
    # this browser didn't start. The course id is recovered from the verified state.
    course_id = _consume_oauth_state(request.args.get('state'))
    if course_id is None:
        return (
            "This authorization request could not be verified. It may have expired, "
            "or it was not started from this browser. Please close this window and "
            "relaunch the tool from Canvas."
        ), 400

    # Exchange code for a token using the API_CLIENT_SECRET
    payload = {
        'grant_type': 'authorization_code',
        'client_id': API_CLIENT_ID,
        'client_secret': API_CLIENT_SECRET,
        'redirect_uri': API_REDIRECT_URI,
        'code': code
    }
    
    try:
        response = requests.post(f"{CANVAS_DOMAIN}/login/oauth2/token", data=payload, timeout=(5, 30))
    except requests.exceptions.RequestException:
        return "Could not reach Canvas to finish authorization. Please close this window and relaunch the tool from Canvas.", 502

    # Canvas' error body (e.g. "invalid_grant") is for the operator's logs, not the
    # user's browser, so it is logged rather than echoed back.
    failure = (
        "Canvas authorization failed. Please close this window and relaunch the tool from Canvas.",
        400,
    )

    if not response.ok:
        current_app.logger.warning("Canvas token exchange failed: %s %s", response.status_code, response.text[:300])
        return failure

    try:
        token_data = response.json()
    except ValueError:
        current_app.logger.warning("Canvas token exchange returned non-JSON: %s", response.text[:300])
        return failure

    if isinstance(token_data, dict) and token_data.get('access_token'):
        session.permanent = True
        store_canvas_token(token_data['access_token'])
        session['canvas_course_id'] = course_id  # Re-store in case session didn't round-trip
        return redirect('/launch_success?' + urllib.parse.urlencode({'course_id': course_id}))

    current_app.logger.warning("Canvas token exchange returned no access_token")
    return failure

@auth_bp.route('/launch_success')
def launch_success():
    # The course id in the query string is informational only; the UI reads the real
    # connection state from GET /api/session.
    return render_app()
