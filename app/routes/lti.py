from flask import Blueprint, request, redirect, session, jsonify
from pylti1p3.contrib.flask import FlaskOIDCLogin, FlaskRequest, FlaskMessageLaunch
from pylti1p3.tool_config import ToolConfJsonFile
from ..utils.lti_utils import get_lti_config_path, get_launch_data_storage
from ..utils.render_utils import _render_with_globals

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

    message_launch = FlaskMessageLaunch(request=flask_request, tool_config=tool_conf, launch_data_storage=launch_data_storage)
    launch_data = message_launch.get_launch_data()
    
    # 1. Capture the Course ID from the LTI Launch Claim
    custom_params = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/custom', {})
    course_id = str(custom_params.get('canvas_course_id', ''))
    
    # 2. Persist state in session
    session['canvas_course_id'] = course_id
    
    # 3. Check for API Token; if missing, start the SECOND OAuth2 flow (API Key)
    if 'canvas_api_token' not in session:
        return redirect('/api/auth/canvas')

    # Token already exists — inject credentials as JS globals and render
    return _render_with_globals('index.html', course_id, session.get('canvas_api_token'))

@lti_bp.route('/jwks/', methods=['GET'])
def get_jwks():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    return jsonify(tool_conf.get_jwks())
