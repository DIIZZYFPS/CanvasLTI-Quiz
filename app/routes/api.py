from flask import Blueprint, request, jsonify, Response, send_file, session
import io
import re
import zipfile
import requests
import os
import urllib.parse
from ..utils.parser import parse_quiz_text
from ..utils.exporter import create_qti_1_2_package
from ..utils.file_reader import read_file

api_bp = Blueprint('api', __name__)

def _sanitize_filename(title):
    """Strip characters that are unsafe in filenames or Content-Disposition headers."""
    sanitized = re.sub(r'[\r\n\x00\\/:"\'*?<>|]', '', title)
    return sanitized.strip() or 'quiz'

@api_bp.route("/preview", methods=['POST'])
def preview():
    if request.content_type.startswith("multipart/form-data"):
        file = request.files.get("file")
        if file:
            content = read_file(file)
            parsed_questions = parse_quiz_text(content)
        else:
            return jsonify({"error": "No file provided"}), 400
    else:
        data = request.get_json()
        parsed_questions = parse_quiz_text(data.get("quiz_text", ""))
    return jsonify({"questions": parsed_questions})

@api_bp.route("/download", methods=['POST'])
def download():
    if request.content_type.startswith("multipart/form-data"):
        title = _sanitize_filename(request.form.get("quiz_title", ""))
        file = request.files.get("file")
        if file:
            content = read_file(file)
            parsed_questions = parse_quiz_text(content)
        else:
            return jsonify({"error": "No file provided"}), 400
    else:
        data = request.get_json()
        title = _sanitize_filename((data.get("quiz_title") or "").strip())
        parsed_questions = parse_quiz_text(data.get("quiz_text", ""))
    
    qti_package = create_qti_1_2_package(title, parsed_questions)

    # Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("quiz.qti.xml", qti_package.encode("utf-8"))

    zip_buffer.seek(0)
    return Response(zip_buffer.read(), mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{title}_package.zip"'
    })

@api_bp.route('/canvas', methods=['POST'])
def canvas():
    data = request.json
    
    # Use course ID from request body if provided, otherwise from session
    course_id = data.get('course_id') or session.get('canvas_course_id')
    # Always use the Canvas API token from the server-side session only
    access_token = session.get('canvas_api_token')

    if not course_id:
        return jsonify({"error": "Missing Canvas Course ID. Please refresh the tool launch."}), 400
    if not access_token:
        # 401 triggers the React frontend to initiate OAuth
        return jsonify({"error": "Missing Canvas API Token, please authorize"}), 401

    title = _sanitize_filename((data.get("quiz_title") or "").strip())
    parsed_questions = parse_quiz_text(data.get("quiz_text", ""))
    qti_package = create_qti_1_2_package(title, parsed_questions)

    # 1. Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("quiz.qti.xml", qti_package.encode("utf-8"))
    
    zip_buffer.seek(0)
    zip_content = zip_buffer.read()
    zip_size = len(zip_content)

    CANVAS_DOMAIN = os.getenv('CANVAS_DOMAIN')
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    try:
        # STEP 1: Initiate Content Migration
        mig_url = f"{CANVAS_DOMAIN}/api/v1/courses/{course_id}/content_migrations"
        mig_payload = {
            'migration_type': 'qti_converter',
            'pre_attachment': {
                'name': f'{title}.zip',
                'size': zip_size,
                'content_type': 'application/zip'
            }
        }
        
        mig_res = requests.post(mig_url, json=mig_payload, headers=headers)
        
        # If Canvas says the token is invalid/expired, clear it and ask for re-auth
        if mig_res.status_code == 401:
            session.pop('canvas_api_token', None)
            return jsonify({"error": "Canvas token expired. Please close and relaunch the tool."}), 401
        
        mig_res.raise_for_status()
        migration_data = mig_res.json()
        
        pre_auth = migration_data.get('pre_attachment', {})
        upload_url = pre_auth.get('upload_url')
        upload_params = pre_auth.get('upload_params', {})
        progress_url = migration_data.get('progress_url')
        
        if not upload_url:
            raise Exception("Failed to receive upload_url from Canvas")

        # STEP 2: Upload File Data
        files = {'file': (f'{title}.zip', zip_content, 'application/zip')}
        
        # Upload the file without following redirects so we can explicitly handle
        # the Canvas redirect behavior and surface real errors.
        upload_res = requests.post(
            upload_url,
            data=upload_params,
            files=files,
            allow_redirects=False
        )

        # If Canvas says the token is invalid/expired during upload, clear it and ask for re-auth
        if upload_res.status_code == 401:
            session.pop('canvas_api_token', None)
            return jsonify({"error": "Canvas token expired during upload. Please close and relaunch the tool."}), 401

        # Treat 2xx as success and 3xx as the expected redirect handoff.
        if 200 <= upload_res.status_code < 300:
            pass
        elif 300 <= upload_res.status_code < 400:
            # Expected behavior: Canvas returns a redirect after a successful upload.
            # We do not follow it here to avoid spurious 401s from downstream endpoints.
            pass
        else:
            # Any other status is an error; raise so the outer HTTPError handler can respond.
            upload_res.raise_for_status()
        
        # Return the progress URL so the React frontend can poll it
        return jsonify({
            "message": "Upload initiated successfully", 
            "progress_url": progress_url
        })
        
    except requests.exceptions.HTTPError as e:
        error_msg = e.response.text if hasattr(e.response, 'text') else str(e)
        return jsonify({"error": f"Canvas API Error: {error_msg}"}), 500
    except Exception as e:
        return jsonify({"error": f"Internal Server Error: {str(e)}"}), 500

@api_bp.route('/proxy/progress', methods=['GET'])
def proxy_progress():
    # Helper endpoint for React to poll progress without dealing with CORS.
    # The Canvas token is read from the server-side session only and never from the client.
    access_token = session.get('canvas_api_token')
    progress_url = request.args.get('url')
    
    if not access_token or not progress_url:
        return jsonify({"error": "Missing token or url"}), 400

    # SSRF protection: restrict to the configured Canvas domain and expected path
    CANVAS_DOMAIN = os.getenv('CANVAS_DOMAIN', '').rstrip('/')
    try:
        parsed = urllib.parse.urlparse(progress_url)
        canvas_parsed = urllib.parse.urlparse(CANVAS_DOMAIN)
        if parsed.netloc != canvas_parsed.netloc or not parsed.path.startswith('/api/v1/progress/'):
            return jsonify({"error": "Invalid progress URL"}), 400
    except Exception:
        return jsonify({"error": "Invalid progress URL"}), 400
        
    try:
        res = requests.get(progress_url, headers={"Authorization": f"Bearer {access_token}"})
        res.raise_for_status()
        return jsonify(res.json())
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/instructions')
def download_instructions():
    # Use absolute path relative to this file
    file_path = os.path.join(os.path.dirname(__file__), '..', 'public', 'Instructions.txt')
    return send_file(
        file_path,
        as_attachment=True,
        download_name="Quiz Reformatting Instructions.txt",
    )
