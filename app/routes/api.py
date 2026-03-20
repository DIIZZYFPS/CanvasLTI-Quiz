from flask import Blueprint, request, jsonify, Response, send_file, session
import io
import zipfile
import requests
import os
from ..utils.parser import parse_quiz_text
from ..utils.exporter import create_qti_1_2_package
from ..utils.file_reader import read_file

api_bp = Blueprint('api', __name__)

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
        title = request.form.get("quiz_title", "quiz")
        file = request.files.get("file")
        if file:
            content = read_file(file)
            parsed_questions = parse_quiz_text(content)
        else:
            return jsonify({"error": "No file provided"}), 400
    else:
        data = request.get_json()
        title = data.get("quiz_title", "quiz")
        parsed_questions = parse_quiz_text(data.get("quiz_text", ""))
    
    qti_package = create_qti_1_2_package(title, parsed_questions)

    # Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("quiz.qti.xml", qti_package.encode("utf-8"))

    zip_buffer.seek(0)
    return Response(zip_buffer.read(), mimetype="application/zip", headers={
        "Content-Disposition": f"attachment; filename={title}_package.zip"
    })

@api_bp.route('/canvas', methods=['POST'])
def canvas():
    data = request.json
    
    # Prioritize credentials from request body, then session
    course_id = data.get('course_id') or session.get('canvas_course_id')
    access_token = data.get('canvas_api_token') or session.get('canvas_api_token')

    if not course_id:
        return jsonify({"error": "Missing Canvas Course ID. Please refresh the tool launch."}), 400
    if not access_token:
        # 401 triggers the React frontend to initiate OAuth
        return jsonify({"error": "Missing Canvas API Token, please authorize"}), 401

    title = data.get("quiz_title", "quiz")
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
        
        # Requests will automatically follow the 3xx redirect to create_success, 
        # which will throw a 401 due to our strict scopes. We expect this and ignore it.
        try:
            requests.post(upload_url, data=upload_params, files=files)
        except requests.exceptions.RequestException as e:
            if e.response is not None and e.response.status_code == 401:
                # Expected behavior: The file already uploaded successfully before the redirect
                pass
            else:
                raise e
        
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
    # Helper endpoint for React to poll progress without dealing with CORS
    # or exposing the token to the frontend
    access_token = request.args.get('token') or session.get('canvas_api_token')
    progress_url = request.args.get('url')
    
    if not access_token or not progress_url:
        return jsonify({"error": "Missing token or url"}), 400
        
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
