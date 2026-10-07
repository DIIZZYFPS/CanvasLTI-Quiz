from flask import Blueprint, request, jsonify, send_file, session, current_app
import io
import re
import zipfile
import requests
import os
import urllib.parse
from werkzeug.exceptions import HTTPException
from ..utils.parser import parse_quiz_text
from ..utils.exporter import create_qti_1_2_package
from ..utils.file_reader import read_file

api_bp = Blueprint('api', __name__)

# (connect, read) timeouts for Canvas calls. Without them a slow or unreachable
# Canvas pins a worker thread indefinitely, and the app runs with few threads.
CANVAS_API_TIMEOUT = (5, 30)
CANVAS_UPLOAD_TIMEOUT = (5, 120)

MAX_TITLE_LENGTH = 200

def _sanitize_filename(title):
    """Make a title safe to use as a file name (zip name, Canvas attachment name).

    This is for file names only. The quiz title shown in Canvas goes through
    _clean_title, which keeps punctuation like apostrophes and colons.
    """
    sanitized = re.sub(r'[\r\n\x00\\/:"\'*?<>|]', '', title)
    sanitized = re.sub(r'\s+', ' ', sanitized)
    return sanitized.strip() or 'quiz'

def _clean_title(raw):
    """Normalise a user-supplied quiz title for display inside the QTI package.

    Only strips what can't be represented (control characters, which are
    invalid in XML) and collapses whitespace. It deliberately keeps characters
    like ' : / and non-ASCII text so "Bob's Quiz: Week 3 - Intro" reaches Canvas
    unchanged; _sanitize_filename is applied separately for file names.
    """
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        raise ValueError("The quiz title must be text.")
    title = re.sub(r'[\x00-\x1f\x7f]', ' ', raw)
    title = re.sub(r'\s+', ' ', title).strip()[:MAX_TITLE_LENGTH].strip()
    return title or 'quiz'

def _canvas_error_message(response):
    """A short, user-safe description of a failed Canvas API response.

    Canvas error bodies are returned as raw text/JSON; surfacing them verbatim
    shows users JSON blobs and can expose internals, so the raw body is logged
    instead and only Canvas' own human-readable message is passed on.
    """
    status = getattr(response, "status_code", None)
    current_app.logger.warning("Canvas API error %s: %s", status, (getattr(response, "text", "") or "")[:500])

    detail = ""
    try:
        body = response.json()
        errors = body.get("errors") if isinstance(body, dict) else None
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            detail = str(errors[0].get("message") or "").strip()
    except ValueError:
        pass

    message = f"Canvas rejected the request (HTTP {status})" if status else "Canvas rejected the request"
    return f"{message}: {detail}" if detail else f"{message}."

def _json_body():
    """The request's JSON body as a dict ({} if absent, malformed, or not an object)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}

def _json_text(data, key):
    """A string field from a JSON body, rejecting non-string values with a 400-able error."""
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be text.")
    return value

def _validate_for_export(questions):
    """Refuse to export a quiz that is empty or still contains parse errors.

    The preview UI already blocks this, but the API is the real gate: the
    preview can be stale, and other clients can call the endpoints directly.
    Without it, error questions were silently dropped and the user got a
    "successful" export that was missing questions.
    """
    if not questions:
        raise ValueError("No questions were found. Add at least one question before exporting.")

    # Numbered the same way as the preview ("Question N" = Nth block).
    bad = [(i, q) for i, q in enumerate(questions, 1) if q.get("type") == "error"]
    if bad:
        shown = "; ".join(f"Question {i}: {q.get('error', 'Unknown error')}" for i, q in bad[:3])
        extra = f" (and {len(bad) - 3} more)" if len(bad) > 3 else ""
        raise ValueError(
            f"{len(bad)} question{'s' if len(bad) != 1 else ''} "
            f"ha{'ve' if len(bad) != 1 else 's'} errors and can't be exported. {shown}{extra}"
        )

def _build_qti_zip(title, questions):
    """Validate the parsed questions and return the QTI package as zip bytes."""
    _validate_for_export(questions)
    qti_package = create_qti_1_2_package(title, questions)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("quiz.qti.xml", qti_package.encode("utf-8"))
    return zip_buffer.getvalue()

@api_bp.route("/preview", methods=['POST'])
def preview():
    try:
        if request.content_type and request.content_type.startswith("multipart/form-data"):
            file = request.files.get("file")
            if file:
                content = read_file(file)
                parsed_questions = parse_quiz_text(content)
            else:
                return jsonify({"error": "No file provided"}), 400
        else:
            data = _json_body()
            parsed_questions = parse_quiz_text(_json_text(data, "quiz_text"))
        return jsonify({"questions": parsed_questions})
    except HTTPException:
        raise  # e.g. 413 request too large: let Flask's handler answer, not a 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        current_app.logger.exception("Preview failed")
        return jsonify({"error": "Failed to process preview"}), 500

@api_bp.route("/download", methods=['POST'])
def download():
    try:
        if request.content_type and request.content_type.startswith("multipart/form-data"):
            title = _clean_title(request.form.get("quiz_title", ""))
            file = request.files.get("file")
            if file:
                content = read_file(file)
                parsed_questions = parse_quiz_text(content)
            else:
                return jsonify({"error": "No file provided"}), 400
        else:
            data = _json_body()
            title = _clean_title(data.get("quiz_title"))
            parsed_questions = parse_quiz_text(_json_text(data, "quiz_text"))

        zip_bytes = _build_qti_zip(title, parsed_questions)

        # send_file emits an RFC 6266 header (ASCII fallback plus filename*=UTF-8''...).
        # A hand-built `filename="{title}"` header cannot carry non-Latin-1 characters
        # such as an en dash or curly apostrophe: the server aborts the response.
        return send_file(
            io.BytesIO(zip_bytes),
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{_sanitize_filename(title)}_package.zip",
        )
    except HTTPException:
        raise
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        current_app.logger.exception("Download failed")
        return jsonify({"error": "Failed to generate the download package."}), 500

@api_bp.route('/canvas', methods=['POST'])
def canvas():
    try:
        data = _json_body()

        # Use course ID from request body if provided, otherwise from session
        course_id = data.get('course_id') or session.get('canvas_course_id')
        # Always use the Canvas API token from the server-side session only
        access_token = session.get('canvas_api_token')

        if not course_id:
            return jsonify({"error": "Missing Canvas Course ID. Please refresh the tool launch."}), 400
        if not access_token:
            # 401 triggers the React frontend to initiate OAuth
            return jsonify({"error": "Missing Canvas API Token, please authorize"}), 401

        # Validate before touching Canvas so a bad quiz never creates a
        # migration. Handled here (not by a blanket ValueError handler) because
        # requests' JSONDecodeError is also a ValueError.
        try:
            title = _clean_title(data.get("quiz_title"))
            parsed_questions = parse_quiz_text(_json_text(data, "quiz_text"))
            zip_content = _build_qti_zip(title, parsed_questions)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        zip_size = len(zip_content)
        zip_name = f"{_sanitize_filename(title)}.zip"

        CANVAS_DOMAIN = os.getenv('CANVAS_DOMAIN')
        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        # STEP 1: Initiate Content Migration
        mig_url = f"{CANVAS_DOMAIN}/api/v1/courses/{course_id}/content_migrations"
        mig_payload = {
            'migration_type': 'qti_converter',
            'pre_attachment': {
                'name': zip_name,
                'size': zip_size,
                'content_type': 'application/zip'
            }
        }
        
        mig_res = requests.post(mig_url, json=mig_payload, headers=headers, timeout=CANVAS_API_TIMEOUT)
        
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
        files = {'file': (zip_name, zip_content, 'application/zip')}
        
        # Upload the file without following redirects so we can explicitly handle
        # the Canvas redirect behavior and surface real errors.
        upload_res = requests.post(
            upload_url,
            data=upload_params,
            files=files,
            allow_redirects=False,
            timeout=CANVAS_UPLOAD_TIMEOUT,
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
        
    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        return jsonify({"error": "Canvas took too long to respond. Please try again in a moment."}), 504
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": _canvas_error_message(e.response)}), 502
    except Exception:
        current_app.logger.exception("Canvas upload failed")
        return jsonify({"error": "Failed to upload to Canvas. Please try again, or use Export QTI and import the file manually."}), 500

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
        res = requests.get(progress_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=CANVAS_API_TIMEOUT)
        res.raise_for_status()
        return jsonify(res.json())
    except requests.exceptions.Timeout:
        return jsonify({"error": "Canvas took too long to respond. Please try again."}), 504
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": _canvas_error_message(e.response)}), 502
    except requests.exceptions.RequestException:
        current_app.logger.exception("Canvas progress check failed")
        return jsonify({"error": "Could not check the upload progress with Canvas."}), 502

@api_bp.route('/instructions')
def download_instructions():
    # Use absolute path relative to this file
    file_path = os.path.join(os.path.dirname(__file__), '..', 'public', 'Instructions.txt')
    return send_file(
        file_path,
        as_attachment=True,
        download_name="Quiz Reformatting Instructions.txt",
    )
