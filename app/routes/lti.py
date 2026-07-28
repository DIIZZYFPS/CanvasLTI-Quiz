from flask import Blueprint, request, redirect, session, jsonify
from pylti1p3.contrib.flask import FlaskOIDCLogin, FlaskRequest, FlaskMessageLaunch
from pylti1p3.tool_config import ToolConfJsonFile
from ..utils.lti_utils import get_lti_config_path, get_launch_data_storage, ExtendedFlaskMessageLaunch
from ..utils.render_utils import _render_with_globals, clean_course_id

lti_bp = Blueprint('lti', __name__)

@lti_bp.route('/login/', methods=['POST', 'GET'])
def login():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    launch_data_storage = get_launch_data_storage()

    flask_request = FlaskRequest()
    target_link_uri = flask_request.get_param('target_link_uri')
    if not target_link_uri:
        target_link_uri = flask_request.get_param('redirect_uri')

    oidc_login = FlaskOIDCLogin(flask_request, tool_conf, launch_data_storage=launch_data_storage)
    return oidc_login.redirect(target_link_uri)

@lti_bp.route('/launch/', methods=['POST'])
def launch():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    flask_request = FlaskRequest()
    launch_data_storage = get_launch_data_storage()
    message_launch = ExtendedFlaskMessageLaunch(request=flask_request, tool_config=tool_conf, launch_data_storage=launch_data_storage)
    launch_data = message_launch.get_launch_data()

    # 1. Capture the Course ID from the LTI Launch Claim with robust fallbacks
    custom_params = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/custom', {})
    
    # Try different potential keys for course ID
    course_id = (
        custom_params.get('canvas_course_id') or 
        custom_params.get('course_id') or 
        custom_params.get('custom_canvas_course_id') or 
        custom_params.get('custom_course_id')
    )
    
    # If not found in custom params, try context claim ID as a last resort fallback
    if not course_id:
        context_claim = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/context', {})
        course_id = context_claim.get('id')
        
    course_id = clean_course_id(course_id)

    # 2. Persist state in session
    session['canvas_course_id'] = course_id
    
    # 3. Check for API Token; if missing, start the SECOND OAuth2 flow (API Key)
    if 'canvas_api_token' not in session:
        return redirect(f'/api/auth/canvas?course_id={course_id}')

    # Token already exists — redirect to launch_success GET endpoint to prevent nonce reissue on refresh
    return redirect(f'/launch_success?course_id={course_id}')

@lti_bp.route('/jwks/', methods=['GET'])
def get_jwks():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    return jsonify(tool_conf.get_jwks())
