from linecache import cache
from pprint import pprint
from flask import Flask, jsonify, send_from_directory, render_template, Response, request, send_file, redirect
from flask_caching import Cache
# ... (imports)
import io
import zipfile
import xml.etree.ElementTree as ET
import xml.dom.minidom
import re
import os
import requests
import urllib.parse
from tempfile import mkdtemp
from dotenv import load_dotenv

from pylti1p3.contrib.flask import FlaskOIDCLogin, FlaskMessageLaunch, FlaskRequest, FlaskCacheDataStorage
from pylti1p3.registration import Registration
from pylti1p3.tool_config import ToolConfJsonFile

load_dotenv()
CANVAS_DOMAIN = os.getenv('CANVAS_DOMAIN', 'http://canvas.docker:8081')
CANVAS_CLIENT_ID = os.getenv('CANVAS_CLIENT_ID')
CANVAS_CLIENT_SECRET = os.getenv('CANVAS_CLIENT_SECRET')
CANVAS_OAUTH_REDIRECT_URI = os.getenv('CANVAS_OAUTH_REDIRECT_URI', 'http://localhost:5000/api/auth/callback')

SESSION_DIR = os.getenv('SESSION_FILE_DIR', '/tmp/flask_session')
if not os.path.exists(SESSION_DIR):
    os.makedirs(SESSION_DIR, exist_ok=True)

app = Flask(__name__, static_folder="assets", template_folder="templates")

config = {
    "DEBUG": False,
    "ENV": "production",
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 600,
    "SECRET_KEY": os.getenv("SECRET_KEY", "replace-me-in-production"),
    "SESSION_TYPE": "filesystem",
    "SESSION_FILE_DIR": SESSION_DIR,
    "SESSION_COOKIE_NAME": "pylti1p3-flask-app-sessionid",
    "SESSION_COOKIE_HTTPONLY": True,
    "SESSION_COOKIE_SECURE": True,    # Must be True on Railway (HTTPS)
    "SESSION_COOKIE_SAMESITE": 'None', # Must be None for cross-site LTI iframes
    "DEBUG_TB_INTERCEPT_REDIRECTS": False
}
app.config.from_mapping(config)
cache = Cache(app)


# LTI ( In Development )

class ExtendedFlaskMessageLaunch(FlaskMessageLaunch):

    def validate_nonce(self):
        """
        Probably it is bug on "https://lti-ri.imsglobal.org":
        site passes invalid "nonce" value during deep links launch.
        Because of this in case of iss == http://imsglobal.org just skip nonce validation.

        """
        iss = self.get_iss()
        deep_link_launch = self.is_deep_link_launch()
        if iss == "http://imsglobal.org" and deep_link_launch:
            return self
        return super().validate_nonce()

import tempfile

def get_lti_config_path():
    base_path = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_path, 'config', 'config.json')
    
    # Check if we are in a serverless env (missing private key on disk)
    private_key_path = os.path.join(base_path, 'config', 'private.key')
    
    if not os.path.exists(private_key_path):
        env_key = os.environ.get("LTI_PRIVATE_KEY")
        if env_key:
            # 1. Prepare /tmp paths
            tmp_dir = tempfile.gettempdir()
            tmp_priv_path = os.path.join(tmp_dir, 'private.key')
            tmp_pub_path = os.path.join(tmp_dir, 'public.key')
            
            # 2. Write Private Key from Env
            with open(tmp_priv_path, 'w') as f:
                f.write(env_key)
            
            # 3. Copy Public Key from source to /tmp (since it exists in your repo)
            src_pub_path = os.path.join(base_path, 'config', 'public.key')
            if os.path.exists(src_pub_path):
                import shutil
                shutil.copy2(src_pub_path, tmp_pub_path)
            
            # 4. Generate the ephemeral config pointing to /tmp for BOTH keys
            return create_ephemeral_config(config_path, tmp_priv_path, tmp_pub_path)

    return config_path

def create_ephemeral_config(original_path, actual_priv_path, actual_pub_path):
    import json
    with open(original_path, 'r') as f:
        config_data = json.load(f)
    
    for issuer in config_data:
        for config_entry in config_data[issuer]:
            config_entry["private_key_file"] = actual_priv_path
            config_entry["public_key_file"] = actual_pub_path # Map the public key too
        
    tmp_config_path = os.path.join(tempfile.gettempdir(), 'config.json')
    with open(tmp_config_path, 'w') as f:
        json.dump(config_data, f)
        
    return tmp_config_path
    
def get_launch_data_storage():
    return FlaskCacheDataStorage(cache)

def get_jwk_from_public_key(key_name):
    key_path = os.path.join(app.root_path, 'config', key_name)
    with open(key_path, 'rb') as key_file:
        public_key = key_file.read()
        jwk = Registration.get_jwk(public_key)
        return jwk



@app.route('/login/', methods=['POST', 'GET'])
def login():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    launch_data_storage = get_launch_data_storage()

    flask_request = FlaskRequest()
    target_link_uri = flask_request.get_param('target_link_uri')
    if not target_link_uri:
        target_link_uri = flask_request.get_param('redirect_uri')

    oidc_login = FlaskOIDCLogin(flask_request, tool_conf, launch_data_storage=launch_data_storage)
    return oidc_login.redirect(target_link_uri)


@app.route('/launch/', methods=['POST'])
def launch():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    flask_request = FlaskRequest()
    launch_data_storage = get_launch_data_storage()

    message_launch = FlaskMessageLaunch(request=flask_request, tool_config=tool_conf, launch_data_storage=launch_data_storage)
    launch_data = message_launch.get_launch_data()
    
    # DEBUG: Print launch data to identify the numeric Course ID key
    print("--- LTI LAUNCH DATA ---")
    import json
    print(json.dumps(launch_data, indent=2))
    print("-----------------------")
    
    # Extract Course ID
    course_id = None
    
    # 1. Check for Canvas custom claim (Most reliable for numeric ID)
    custom_params = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/custom', {})
    if custom_params.get('canvas_course_id'):
        course_id = str(custom_params.get('canvas_course_id'))
    
    # 2. Fallback: Parse from Names and Roles service URL
    if not course_id or not course_id.isdigit():
        nrps_claim = launch_data.get('https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice', {})
        url = nrps_claim.get('context_memberships_url', '')
        if '/courses/' in url:
            course_id = url.split('/courses/')[1].split('/')[0]
            
    # 3. Last Resort: Standard context claim (often an opaque hash)
    if not course_id:
        context_claim = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/context', {})
        course_id = context_claim.get('id')

    from flask import session, redirect
    if course_id:
        session['canvas_course_id'] = course_id
        print(f"--- FINAL DETECTED COURSE ID: {course_id} ---")

    # If no token in session, immediately redirect to Canvas OAuth before loading the app.
    # Pass course_id as a URL param — don't rely on session surviving the cross-site POST redirect.
    if 'canvas_api_token' not in session:
        print("--- No canvas_api_token in session, redirecting to OAuth ---")
        return redirect(f'/api/auth/canvas?course_id={course_id or ""}')

    # Token exists — render the app and inject credentials into global JS variables
    html = render_template('index.html', course_id=course_id, has_token=True)
    
    injections = []
    if course_id:
        injections.append(f'window.CANVAS_COURSE_ID = "{course_id}";')
    injections.append(f'window.CANVAS_API_TOKEN = "{session.get("canvas_api_token")}";')
    
    script = f'<script>{" ".join(injections)}</script>'
    html = html.replace('<head>', f'<head>{script}')
    
    return html

@app.route('/jwks/', methods=['GET'])
def get_jwks():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    return jsonify(tool_conf.get_jwks())

@app.route('/favicon.ico')
def favicon():
    return '', 204

# ---------------------------------------------
# Canvas OAuth2 Endpoints
# ---------------------------------------------
@app.route('/api/auth/canvas', methods=['GET'])
def auth_canvas():
    scopes = ' '.join([
        'url:POST|/api/v1/courses/:course_id/content_migrations',
        'url:GET|/api/v1/progress/:id',
        'url:POST|/api/v1/courses/:course_id/files'
    ])
    
    from flask import session
    # course_id comes from the redirect URL param (most reliable) or session as fallback
    course_id = request.args.get('course_id') or session.get('canvas_course_id', '')
    if course_id:
        session['canvas_course_id'] = course_id  # Ensure it's in session
    print(f"--- auth_canvas: course_id={course_id!r} ---")
    auth_url = f"{CANVAS_DOMAIN}/login/oauth2/auth?" + urllib.parse.urlencode({
        'client_id': CANVAS_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': CANVAS_OAUTH_REDIRECT_URI,
        'scopes': scopes,
        'state': course_id
    })
    
    return redirect(auth_url)

@app.route('/api/auth/callback', methods=['GET'])
def auth_callback():
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        return f"Authorization Error: {error}", 400
        
    if not code:
        return "Missing authorization code", 400
        
    # Exchange code for token
    token_url = f"{CANVAS_DOMAIN}/login/oauth2/token"
    payload = {
        'grant_type': 'authorization_code',
        'client_id': CANVAS_CLIENT_ID,
        'client_secret': CANVAS_CLIENT_SECRET,
        'redirect_uri': CANVAS_OAUTH_REDIRECT_URI,
        'code': code
    }
    
    try:
        req = requests.post(token_url, data=payload)
        req.raise_for_status()
        token_data = req.json()
        
        from flask import session
        session['canvas_api_token'] = token_data.get('access_token')
        
        # Recover course_id from OAuth state param as a fallback if session didn't round-trip
        course_id = session.get('canvas_course_id') or request.args.get('state') or ''
        if course_id:
            session['canvas_course_id'] = course_id  # Re-store in case it was lost

        # Re-render the app with credentials injected
        html = render_template('index.html', course_id=course_id, has_token=True)
        
        injections = []
        if course_id:
            injections.append(f'window.CANVAS_COURSE_ID = "{course_id}";')
        injections.append(f'window.CANVAS_API_TOKEN = "{session.get("canvas_api_token")}";')
        
        script = f'<script>{" ".join(injections)}</script>'
        html = html.replace('<head>', f'<head>{script}')
        
        return html
    except Exception as e:
        return f"Error exchanging token: {str(e)}", 500

# Helpers

def extract_points(text, default="1"):
    """
    Extracts points from a string in various formats:
    - (10 points), (5 pts)
    - Points: 10, Score: 10
    Returns the points as a string, e.g., "10".
    """
    pattern = re.compile(
        r'(?:'
        r'[\(\[]\s*\b(?:Points?|Score|Pts?)\b:?\s*(?P<label_bracketed>\d+)\s*[\)\]]'  # [Points: 10], (Score 5)
        r'|'
        r'\b(?:Points?|Score|Pts?)\b:?\s*(?P<label>\d+)'                              # Points: 10
        r'|'
        r'\(\s*(?P<numeric_first>\d+)\s*(?:points?|pts?)\s*\)'                        # (10 points), (5 pts)
        r')',
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match:
        for group_name in ("label_bracketed", "label", "numeric_first"):
            value = match.group(group_name)
            if value is not None:
                return value
    return default

def _clean_points_text(text):
    """Removes the points string from the question text to clean it up."""
    return re.sub(
        r'(?:'
        r'[\(\[]\s*\b(?:Points?|Score|Pts?)\b:?\s*\d+\s*[\)\]]'   # [Points: 10], (Score 5)
        r'|'
        r'\b(?:Points?|Score|Pts?)\b:?\s*\d+'                    # Points: 10
        r'|'
        r'\(\s*\d+\s*(?:points?|pts?)\s*\)'                      # (10 points), (5 pts)
        r')',
        '',
        text,
        flags=re.IGNORECASE,
    ).strip()

def _parse_multiple_choice(lines, index):
    """Parses a multiple-choice question with diagnostic error messages."""
    full_text = " ".join(lines)
    points = extract_points(full_text)
    
    # 1. Extract Answer
    answer_match = re.search(r'Answer:\s*([A-Z])', full_text, re.IGNORECASE)
    if not answer_match:
        return {
            "id": f"error_{index}",
            "type": "error",
            "question_text": full_text,
            "error": "Missing or Invalid Answer. Ensure the question ends with 'Answer: [Letter]' (e.g., 'Answer: B')."
        }
    correct_char = answer_match.group(1).upper()

    # 2. Extract Options
    options = []
    # Identify lines starting with "A)", "B.", etc.
    for line in lines:
        match = re.match(r'^([A-Z])[\)\.]\s*(.*)', line.strip())
        if match:
            options.append({"id": match.group(1).upper(), "text": match.group(2).strip()})
    
    if len(options) < 2:
        return {
            "id": f"error_{index}", 
            "type": "error", 
            "question_text": full_text, 
            "error": "Insufficient options found. List at least two options starting with 'A)', 'B)', etc."
        }

    # 3. Extract Question Text (everything before the first option)
    question_lines = []
    for line in lines:
        if re.match(r'^[A-Z][\)\.]', line.strip()):
            break
        question_lines.append(line)
    
    question_text = " ".join(question_lines).strip()
    question_text = _clean_points_text(question_text)

    if not question_text:
        return {"id": f"error_{index}", "type": "error", "question_text": full_text, "error": "Question text is missing. The question prompt must appear before the options."}

    # 4. Validate Answer matches an Option
    correct_answer_id = None
    answers = []
    
    for i, opt in enumerate(options):
        ans_id = f"q{index}_ans{i}"
        answers.append({"id": ans_id, "text": opt['text']})
        if opt['id'] == correct_char:
            correct_answer_id = ans_id
            
    if not correct_answer_id:
        valid_options = ", ".join([o['id'] for o in options])
        return {
            "id": f"error_{index}", 
            "type": "error", 
            "question_text": question_text, 
            "error": f"The answer '{correct_char}' does not match any of the provided options ({valid_options})."
        }

    return {
        "id": f"q{index}", 
        "type": "multiple_choice_question", 
        "question_text": question_text,
        "answers": answers, 
        "correct_answer_id": correct_answer_id, 
        "points": points
    }

def _parse_true_false(lines, index):
    """Parses a true/false question with diagnostic error messages."""
    full_text = " ".join(lines)
    points = extract_points(full_text)
    
    # 1. Clean up prefix if present
    clean_text = re.sub(r'^(?:TF:|True/False:)\s*', '', full_text, flags=re.IGNORECASE)
    
    # 2. Find Answer
    answer_match = re.search(r'Answer:\s*(T|True|F|False)', clean_text, re.IGNORECASE)
    
    if not answer_match:
        return {
            "id": f"error_{index}",
            "type": "error",
            "question_text": full_text,
            "error": "Missing or Invalid Answer. Ensure the question ends with 'Answer: True' or 'Answer: False'."
        }

    # 3. Extract Question Text
    question_part = re.split(r'Answer:', clean_text, flags=re.IGNORECASE)[0].strip()
    question_part = re.sub(r'\((?:T/F|True/False)\)', '', question_part, flags=re.IGNORECASE) # Remove (T/F) hint
    question_part = _clean_points_text(question_part)

    if not question_part:
        return {
            "id": f"error_{index}",
            "type": "error",
            "question_text": full_text,
            "error": "Question text is empty."
        }

    correct_str = answer_match.group(1).lower()
    is_true = correct_str in ['t', 'true']
    
    answers = [{"id": f"q{index}_ans0", "text": "True"}, {"id": f"q{index}_ans1", "text": "False"}]
    correct_answer_id = answers[0]['id'] if is_true else answers[1]['id']

    return {
        "id": f"q{index}", 
        "type": "true_false_question", 
        "question_text": question_part,
        "answers": answers, 
        "correct_answer_id": correct_answer_id, 
        "points": points
    }

def _parse_short_answer(line, index):
    points = extract_points(line)
    
    # Strip prefix
    clean_line = re.sub(r'^(?:SA:|Short Answer:)\s*', '', line, flags=re.IGNORECASE)
    
    # Check for Answer
    parts = re.split(r'Answer:', clean_line, flags=re.IGNORECASE)
    
    if len(parts) < 2:
        return {
            "id": f"error_{index}",
            "type": "error",
            "question_text": line,
            "error": "Missing 'Answer:'. Short Answer questions must end with 'Answer: [Your Answer]'."
        }
        
    question_text = parts[0].strip()
    question_text = re.sub(r'\[Short Answer\]', '', question_text, flags=re.IGNORECASE)
    question_text = _clean_points_text(question_text)
    
    correct_answer = parts[1].strip()
    if not correct_answer:
        return {
            "id": f"error_{index}",
            "type": "error",
            "question_text": line,
            "error": "Answer content is empty."
        }

    return {
        "id": f"q{index}", 
        "type": "short_answer_question", 
        "question_text": question_text,
        "answers": [{"id": f"q{index}_ans0", "text": correct_answer}], 
        "points": points
    }

def _parse_fill_in_the_blank(line, index):
    points = extract_points(line)
    
    parts = re.split(r'Answer:', line, flags=re.IGNORECASE)
    if len(parts) < 2:
        return {
            "id": f"error_{index}",
            "type": "error",
            "question_text": line,
            "error": "Missing 'Answer:'. Fill-in-the-blank questions must end with 'Answer: [word]'."
        }
        
    question_text = parts[0].strip()
    correct_answer = parts[1].strip()
    
    if not re.search(r'_{2,}', question_text):
        return {
            "id": f"error_{index}",
            "type": "error",
            "question_text": line,
            "error": "No blank found. Use underscores (e.g., '_____') to indicate where the blank should be."
        }
    
    question_text = _clean_points_text(question_text)

    return {
        "id": f"q{index}", 
        "type": "fill_in_the_blank_question", 
        "question_text": question_text,
        "answers": [{"id": f"q{index}_ans0", "text": correct_answer}], 
        "points": points
    }


def _parse_essay(line, index):
    """Parses an essay question line."""
    points = extract_points(line)
    
    # Clean up prefixes and tags
    clean_line = re.sub(r'^(?:Essay:)\s*', '', line, flags=re.IGNORECASE)
    clean_line = re.sub(r'\[Essay\]', '', clean_line, flags=re.IGNORECASE)
    question_text = _clean_points_text(clean_line)
    
    if not question_text:
        return {
            "id": f"error_{index}",
            "type": "error",
            "question_text": line,
            "error": "Essay question text is empty."
        }

    return {
        "id": f"q{index}",
        "type": "essay_question",
        "question_text": question_text,
        "answers": [], 
        "points": points
    }

def parse_quiz_text(text_input):
    """
    Correctly parses multi-line quiz questions from a single text block.
    """
    questions = []
    # Split by one or more blank lines to correctly separate each question block
    blocks = re.split(r'\n\s*\n', text_input.strip())
    
    for i, block in enumerate(blocks):
        if not block.strip():
            continue
        print(f"Parsing block {i}: {block}")
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        full_block_text = " ".join(lines) # Used for simple keyword checks
        full_lower = full_block_text.lower()

        question_data = None

        #Removes leading numbering like "1. " or "2) "
        if re.match(r'^\d+[\.\)]\s+', lines[0]):
            lines[0] = re.sub(r'^\d+[\.\)]\s+', '', lines[0])
            full_block_text = " ".join(lines)
            full_lower = full_block_text.lower()
        
        # --- Router logic ---
        
        # 1. Check explicit prefixes first (Highest priority, matching your instructions)
        if full_lower.startswith("tf:") or full_lower.startswith("true/false:"):
            print(f"Detected True/False (Prefix) in block {i}")
            question_data = _parse_true_false(lines, i)

        elif full_lower.startswith("sa:") or "[short answer]" in full_lower:
            print(f"Detected Short Answer (Prefix) in block {i}")
            question_data = _parse_short_answer(full_block_text, i)
        
        elif full_lower.startswith("essay:") or "[essay]" in full_lower:
            print(f"Detected Essay (Prefix) in block {i}")
            question_data = _parse_essay(full_block_text, i)

        # 2. Check Structural Indicators (Fallbacks)
        elif re.search(r'_{2,}', full_block_text) and "answer:" in full_lower:
            print(f"Detected Fill-in-the-Blank (Structure) in block {i}")
            question_data = _parse_fill_in_the_blank(full_block_text, i)

        elif "answer:" in full_lower and re.search(r'\n\s*[A-Z]\)', "\n"+"\n".join(lines), re.IGNORECASE):
            # We join lines here to ensure we are looking for options in the body, not just the single line string
            print(f"Detected Multiple Choice (Structure) in block {i}")
            question_data = _parse_multiple_choice(lines, i)
            
        # 3. Last Resort Legacy Check
        elif "answer:" in full_lower and re.search(r'\((T/F|True/False)\)', full_block_text, re.IGNORECASE):
            print(f"Detected True/False (Legacy Suffix) in block {i}")
            question_data = _parse_true_false(lines, i)

        else:
            # Enhanced Error Identification
            error_hint = "Format not recognized."
            
            if re.search(r'\n[A-Z][\)\.]', "\n"+"\n".join(lines), re.IGNORECASE):
                error_hint = "Looks like Multiple Choice, but check if the 'Answer:' line is correct."
            elif re.search(r'_{1,}', block):
                error_hint = "Looks like Fill-in-the-Blank, but check if 'Answer:' line is present. Or if there are enough underscores for blanks."
            elif "True" in block or "False" in block:
                error_hint = "Looks like True/False. Ensure it ends with 'Answer: True' or 'Answer: False'."

            print(f"Warning: Could not determine question type for block {i}. {error_hint}")
            
            question_data = {
                "id": f"error_{i}",
                "type": "error",
                "question_text": block,
                "error": f"{error_hint} Please refer to the formatting guide.",
            }
        
        if question_data:
            questions.append(question_data)
            
    return questions

def _create_mcq_item(section, question):
    """Builds the XML for a Multiple Choice or True/False question."""
    item = ET.SubElement(section, 'item', {'ident': question['id'], 'title': "Question"})
    
    # Metadata (Points)
    itemmetadata = ET.SubElement(item, 'itemmetadata')
    qtimetadata = ET.SubElement(itemmetadata, 'qtimetadata')
    points_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(points_field, 'fieldlabel').text = 'points_possible'
    ET.SubElement(points_field, 'fieldentry').text = str(float(question['points']))

    # Presentation (Question Text and Answers)
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = f"<div><p>{question['question_text']}</p></div>"
    
    response_lid = ET.SubElement(presentation, 'response_lid', {'ident': 'response1', 'rcardinality': 'Single'})
    render_choice = ET.SubElement(response_lid, 'render_choice')
    
    for answer in question['answers']:
        response_label = ET.SubElement(render_choice, 'response_label', {'ident': answer['id']})
        ans_material = ET.SubElement(response_label, 'material')
        ET.SubElement(ans_material, 'mattext', {'texttype': 'text/plain'}).text = answer['text']
        
    # Response Processing (Scoring)
    resprocessing = ET.SubElement(item, 'resprocessing')
    outcomes = ET.SubElement(resprocessing, 'outcomes')
    ET.SubElement(outcomes, 'decvar', {'maxvalue': '100', 'minvalue': '0', 'varname': 'SCORE', 'vartype': 'Decimal'})
    
    respcondition = ET.SubElement(resprocessing, 'respcondition', {'continue': 'No'})
    conditionvar = ET.SubElement(respcondition, 'conditionvar')
    ET.SubElement(conditionvar, 'varequal', {'respident': 'response1'}).text = question['correct_answer_id']
    ET.SubElement(respcondition, 'setvar', {'action': 'Set', 'varname': 'SCORE'}).text = '100'

def _create_essay_item(section, question):
    """Builds the XML for an Essay question."""
    item = ET.SubElement(section, 'item', {'ident': question['id'], 'title': "Question"})

    # Metadata (Points)
    itemmetadata = ET.SubElement(item, 'itemmetadata')
    qtimetadata = ET.SubElement(itemmetadata, 'qtimetadata')
    points_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(points_field, 'fieldlabel').text = 'points_possible'
    ET.SubElement(points_field, 'fieldentry').text = str(float(question['points']))

    # Presentation (Just the prompt)
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = f"<div><p>{question['question_text']}</p></div>"
    
    # Response container for text entry
    response_str = ET.SubElement(presentation, 'response_str', {'ident': 'response1', 'rcardinality': 'Single'})
    ET.SubElement(response_str, 'render_fib') # Essay questions just need this empty tag
    
    # Response processing is minimal for essays (manual grading)
    ET.SubElement(item, 'resprocessing')

def _create_short_answer_item(section, question):
    """Builds the XML for a Short Answer or Fill in the Blank question."""
    item = ET.SubElement(section, 'item', {'ident': question['id'], 'title': "Question"})

    # Metadata (Points)
    itemmetadata = ET.SubElement(item, 'itemmetadata')
    qtimetadata = ET.SubElement(itemmetadata, 'qtimetadata')
    points_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(points_field, 'fieldlabel').text = 'points_possible'
    ET.SubElement(points_field, 'fieldentry').text = str(float(question['points']))

    # Presentation
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = f"<div><p>{question['question_text']}</p></div>"
    
    response_str = ET.SubElement(presentation, 'response_str', {'ident': 'response1', 'rcardinality': 'Single'})
    ET.SubElement(response_str, 'render_fib')

    # Response Processing (checks for one or more correct answers)
    resprocessing = ET.SubElement(item, 'resprocessing')
    outcomes = ET.SubElement(resprocessing, 'outcomes')
    ET.SubElement(outcomes, 'decvar', {'maxvalue': '100', 'minvalue': '0', 'varname': 'SCORE', 'vartype': 'Decimal'})
    
    respcondition = ET.SubElement(resprocessing, 'respcondition', {'continue': 'No'})
    conditionvar = ET.SubElement(respcondition, 'conditionvar')
    # Add each possible correct answer to the condition
    for answer in question['answers']:
        ET.SubElement(conditionvar, 'varequal', {'respident': 'response1'}).text = answer['text']
    ET.SubElement(respcondition, 'setvar', {'action': 'Set', 'varname': 'SCORE'}).text = '100'

def create_qti_1_2_package(parsed_data, quiz_title="My Uploaded Quiz"):
    """
    Acts as a router, calling the correct XML generation function
    based on the question type.
    """
    # Boilerplate setup
    ns = {'': 'http://www.imsglobal.org/xsd/ims_qtiasiv1p2'}
    ET.register_namespace('', ns[''])
    qti_root = ET.Element('questestinterop')
    assessment = ET.SubElement(qti_root, 'assessment', {'ident': 'assessment_1', 'title': quiz_title})
    section = ET.SubElement(assessment, 'section', {'ident': 'root_section'})

    # --- ROUTER LOGIC ---
    for question in parsed_data:
        q_type = question.get("type")
        
        if q_type in ["multiple_choice_question", "true_false_question"]:
            _create_mcq_item(section, question)
        elif q_type in ["short_answer_question", "fill_in_the_blank_question"]:
            _create_short_answer_item(section, question)
        elif q_type == "essay_question":
            _create_essay_item(section, question)
        else:
            print(f"Warning: Unknown question type '{q_type}' - skipping.")

    # Convert to string and return
    rough_string = ET.tostring(qti_root, xml_declaration=True, encoding='UTF-8')
    reparsed = xml.dom.minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

def read_file(file):
    if file.content_type == "application/pdf":
        import fitz
        file_bytes = file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    elif file.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        from docx import Document
        file_bytes = file.read()
        with io.BytesIO(file_bytes) as file_stream:
            document = Document(file_stream)
            text = "\n".join([para.text for para in document.paragraphs])
        return text
    else:
        return file.read().decode('utf-8')

@app.route("/api/preview", methods=['POST'])
def preview():
    if request.content_type.startswith("multipart/form-data"):
        file = request.files.get("file")
        if file:
            content = read_file(file)
            print(content)
            parsed_questions = parse_quiz_text(content)
        else:
            return {"error": "No file provided"}, 400
    else:
        data = request.get_json()
        parsed_questions = parse_quiz_text(data.get("quiz_text", ""))
    return {"questions": parsed_questions}

@app.route("/api/download", methods=['POST'])
def download():
    if request.content_type.startswith("multipart/form-data"):
        file = request.files.get("file")
        if file:
            content = read_file(file)
            print(content)
            parsed_questions = parse_quiz_text(content)
        else:
            return {"error": "No file provided"}, 400
    else:
        data = request.get_json()
        parsed_questions = parse_quiz_text(data.get("quiz_text", ""))
    qti_package = create_qti_1_2_package(parsed_questions)

    # Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("quiz.qti.xml", qti_package.encode("utf-8"))

    zip_buffer.seek(0)
    return Response(zip_buffer.read(), mimetype="application/zip", headers={
        "Content-Disposition": "attachment; filename=quiz_package.zip"
    })

@app.route('/api/canvas', methods=['POST'])
def canvas():
    from flask import session
    data = request.json
    
    # Prioritize credentials from request body, then session
    course_id = data.get('course_id') or session.get('canvas_course_id')
    access_token = data.get('canvas_api_token') or session.get('canvas_api_token')

    if not course_id:
        return jsonify({"error": "Missing Canvas Course ID. Please refresh the tool launch."}), 400
    if not access_token:
        # 401 triggers the React frontend to initiate OAuth
        return jsonify({"error": "Missing Canvas API Token, please authorize"}), 401

    data = request.json
    parsed_questions = parse_quiz_text(data.get("quiz_text", ""))
    qti_package = create_qti_1_2_package(parsed_questions)

    # 1. Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("quiz.qti.xml", qti_package.encode("utf-8"))
    
    zip_buffer.seek(0)
    zip_content = zip_buffer.read()
    zip_size = len(zip_content)

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    try:
        # STEP 1: Initiate Content Migration
        mig_url = f"{CANVAS_DOMAIN}/api/v1/courses/{course_id}/content_migrations"
        mig_payload = {
            'migration_type': 'qti_converter',
            'pre_attachment': {
                'name': 'quiz_package.zip',
                'size': zip_size,
                'content_type': 'application/zip'
            }
        }
        
        mig_res = requests.post(mig_url, json=mig_payload, headers=headers)
        mig_res.raise_for_status()
        migration_data = mig_res.json()
        
        pre_auth = migration_data.get('pre_attachment', {})
        upload_url = pre_auth.get('upload_url')
        upload_params = pre_auth.get('upload_params', {})
        progress_url = migration_data.get('progress_url')
        
        if not upload_url:
            raise Exception("Failed to receive upload_url from Canvas")

        # STEP 2: Upload File Data
        files = {'file': ('quiz_package.zip', zip_content, 'application/zip')}
        
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


@app.route('/api/proxy/progress', methods=['GET'])
def proxy_progress():
    # Helper endpoint for React to poll progress without dealing with CORS
    # or exposing the token to the frontend
    from flask import session
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
@app.route('/api/instructions')
def download_instructions():
    return send_file(
        "public/Instructions.txt",
        as_attachment=True,
        download_name="Quiz Reformatting Instructions.txt",
    )





@app.route('/assets/<path:filename>')
def assets(filename):
    return send_from_directory(app.static_folder, filename)

@app.route('/')
def index():
    return render_template('index.html')


# Production
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react_app(path):
    """
    Serves the React application. In production, any request that doesn't match
    an LTI or API route will be served the index.html file, allowing
    React Router to handle the frontend routing.
    """
    return render_template('index.html')



# --- Example Usage ---
if __name__ == '__main__':
    app.run(debug=True)