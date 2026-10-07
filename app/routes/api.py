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
from ..utils.session_tokens import get_canvas_token, clear_canvas_token

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

class CanvasUploadError(Exception):
    """A Canvas upload step failed in a way that has a user-presentable message."""


_ID_RE = re.compile(r'\d{1,20}')


def _numeric_id(value):
    """`value` as a digit string if it is a plausible Canvas numeric ID, else None.

    IDs are interpolated into Canvas API paths, so anything else (slashes, '..',
    '?', '#') must never get that far.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    return text if _ID_RE.fullmatch(text) else None


def _is_canvas_url(url):
    """True if `url` has the same scheme and host as the configured CANVAS_DOMAIN."""
    canvas = urllib.parse.urlparse((os.getenv('CANVAS_DOMAIN') or '').rstrip('/'))
    target = urllib.parse.urlparse(url)
    return bool(canvas.netloc) and (target.scheme, target.netloc.lower()) == (canvas.scheme, canvas.netloc.lower())


def _finalize_upload(upload_res, upload_url, access_token):
    """Complete a Canvas file upload that answered with a redirect.

    Canvas's file-upload protocol (step 3) says that when the upload response is a
    3xx redirect, the client must GET the Location - with the Authorization header -
    to confirm the upload; until then the file stays "pending" and the content
    migration never starts. This used to be skipped, so on installs that answer with
    a redirect (rather than a 201) the quiz silently never imported.

    The bearer token is only ever sent to Canvas's own origin.
    """
    location = upload_res.headers.get('Location')
    if not location:
        raise CanvasUploadError("Canvas didn't say how to finish the upload. Please try again.")

    target = urllib.parse.urljoin(upload_url, location)
    if not _is_canvas_url(target):
        current_app.logger.warning("Refusing to follow upload redirect to a non-Canvas host: %s", target)
        raise CanvasUploadError("Canvas sent an unexpected upload redirect, so the upload was stopped.")

    return requests.get(
        target,
        headers={"Authorization": f"Bearer {access_token}"},
        allow_redirects=False,
        timeout=CANVAS_API_TIMEOUT,
    )


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
        raw_course_id = data.get('course_id') or session.get('canvas_course_id')
        # Always use the Canvas API token from the server-side session only
        access_token = get_canvas_token()

        if not raw_course_id:
            return jsonify({"error": "Missing Canvas Course ID. Please refresh the tool launch."}), 400
        course_id = _numeric_id(raw_course_id)
        if course_id is None:
            return jsonify({"error": "That isn't a valid Canvas course ID. Please relaunch the tool from your course."}), 400
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
            clear_canvas_token()
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
            clear_canvas_token()
            return jsonify({"error": "Canvas token expired during upload. Please close and relaunch the tool."}), 401

        if 200 <= upload_res.status_code < 300:
            pass  # uploaded; nothing more to confirm
        elif 300 <= upload_res.status_code < 400:
            # Canvas answers some uploads with a redirect that must be requested, with
            # authorization, to confirm the upload (see _finalize_upload). We don't let
            # `requests` follow it automatically: it would send no Authorization header
            # and get a 401, and we want to control where the token goes.
            finalize_res = _finalize_upload(upload_res, upload_url, access_token)
            if finalize_res.status_code == 401:
                clear_canvas_token()
                return jsonify({"error": "Canvas token expired while finishing the upload. Please close and relaunch the tool."}), 401
            if not 200 <= finalize_res.status_code < 300:
                finalize_res.raise_for_status()
                raise CanvasUploadError("Canvas didn't confirm the upload. Please try again.")
        else:
            # Any other status is an error; raise so the outer HTTPError handler can respond.
            upload_res.raise_for_status()

        # The React frontend polls progress by its numeric id (see /proxy/progress). The
        # URL is returned too for reference, but it is never requested on the client's say-so.
        progress_match = re.fullmatch(r'/api/v1/progress/(\d+)/?', urllib.parse.urlparse(progress_url or '').path)
        return jsonify({
            "message": "Upload initiated successfully",
            "progress_url": progress_url,
            "progress_id": progress_match.group(1) if progress_match else None,
        })

    except HTTPException:
        raise
    except CanvasUploadError as e:
        return jsonify({"error": str(e)}), 502
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
    #
    # The client supplies only a numeric progress id; the URL is built here from the
    # configured CANVAS_DOMAIN. (It used to accept a full URL and try to validate it,
    # which left room for scheme downgrades and '..' path tricks to reach other Canvas
    # endpoints with the user's token.)
    access_token = get_canvas_token()
    progress_id = _numeric_id(request.args.get('id'))
    canvas_domain = (os.getenv('CANVAS_DOMAIN') or '').rstrip('/')

    if not access_token:
        return jsonify({"error": "Missing Canvas API Token, please authorize"}), 401
    if progress_id is None:
        return jsonify({"error": "Missing or invalid progress id"}), 400
    if not canvas_domain:
        return jsonify({"error": "Canvas is not configured on the server"}), 500

    progress_url = f"{canvas_domain}/api/v1/progress/{progress_id}"

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
