from flask import Blueprint, request, redirect, session, jsonify
import requests
import urllib.parse
import os
from ..utils.render_utils import _render_with_globals

auth_bp = Blueprint('auth', __name__)

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
        'state': session.get('canvas_course_id', '') # Pass course_id as state for round-trip
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
    # Recover course_id from OAuth state param — session may not have survived the round-trip
    course_id = request.args.get('state') or session.get('canvas_course_id', '')
    
    if not code:
        return "Missing authorization code", 400

    # Exchange code for a token using the API_CLIENT_SECRET
    payload = {
        'grant_type': 'authorization_code',
        'client_id': API_CLIENT_ID,
        'client_secret': API_CLIENT_SECRET,
        'redirect_uri': API_REDIRECT_URI,
        'code': code
    }
    
    response = requests.post(f"{CANVAS_DOMAIN}/login/oauth2/token", data=payload)

    if not response.ok:
        return jsonify({"error": "Token exchange failed", "details": response.text}), 400

    try:
        token_data = response.json()
    except Exception:
        return jsonify({"error": "Invalid JSON response from Canvas during token exchange"}), 400
    
    if 'access_token' in token_data:
        session.permanent = True
        session['canvas_api_token'] = token_data['access_token']
        session['canvas_course_id'] = course_id  # Re-store in case session didn't round-trip
        return redirect(f'/launch_success?course_id={course_id}')
    
    return jsonify({"error": "Failed to obtain API token", "details": token_data}), 400

@auth_bp.route('/launch_success')
def launch_success():
    course_id = request.args.get('course_id') or session.get('canvas_course_id', '')
    return _render_with_globals('index.html', course_id, session.get('canvas_api_token'))
