from linecache import cache
from pprint import pprint
from flask import Flask, jsonify, send_from_directory, render_template, Response, request, send_file
from flask_caching import Cache
import io
import zipfile
import xml.etree.ElementTree as ET
import xml.dom.minidom
import re
import os
from tempfile import mkdtemp

from pylti1p3.contrib.flask import FlaskOIDCLogin, FlaskMessageLaunch, FlaskRequest, FlaskCacheDataStorage
from pylti1p3.registration import Registration
from pylti1p3.tool_config import ToolConfJsonFile

SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session')
if not os.path.exists(SESSION_DIR):
    os.makedirs(SESSION_DIR)

app = Flask(__name__, static_folder="assets", template_folder="templates")

config = {
    "DEBUG": False,
    "ENV": "production",
    "CACHE_TYPE": "simple",
    "CACHE_DEFAULT_TIMEOUT": 600,
    "SECRET_KEY": "replace-me",
    "SESSION_TYPE": "filesystem",
    "SESSION_FILE_DIR": SESSION_DIR,
    "SESSION_COOKIE_NAME": "pylti1p3-flask-app-sessionid",
    "SESSION_COOKIE_HTTPONLY": True,
    "SESSION_COOKIE_SECURE": True,   # should be True in case of HTTPS usage (production)
    "SESSION_COOKIE_SAMESITE": 'None',  # should be 'None' in case of HTTPS usage (production)
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

def get_lti_config_path():
    return os.path.join(app.root_path, 'config', 'config.json')

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
    return oidc_login\
        .enable_check_cookies()\
        .redirect(target_link_uri)


@app.route('/launch/', methods=['POST'])
def launch():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    flask_request = FlaskRequest()
    launch_data_storage = get_launch_data_storage()

    message_launch = FlaskMessageLaunch(request=flask_request, tool_config=tool_conf, launch_data_storage=launch_data_storage)
    # message_launch_data = message_launch.get_launch_data()

    return render_template('index.html')

@app.route('/jwks/', methods=['GET'])
def get_jwks():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    return jsonify(tool_conf.get_jwks())

# Helpers

def extract_points(text, default="1"):
    """
    Extracts points from a string in various formats:
    - (10 points), (5 pts)
    - Points: 10, Score: 10
    Returns the points as a string, e.g., "10".
    """
    pattern = re.compile(r'(?:(?:\(|\[)?\b(?:Points?|Score|Pts?)\b:?\s*(\d+)(?:\)|\])?)|(?:\(\s*(\d+)\s*(?:points?|pts?)\s*\))', re.IGNORECASE)
    match = pattern.search(text)
    if match:
        return match.group(1) or match.group(2)
    return default

def _clean_points_text(text):
    """Removes the points string from the question text to clean it up."""
    return re.sub(r'(?:(?:\(|\[)?\b(?:Points?|Score|Pts?)\b:?\s*(\d+)(?:\)|\])?)|(?:\(\s*(\d+)\s*(?:points?|pts?)\s*\))', '', text, flags=re.IGNORECASE).strip()

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
            
            if re.search(r'\n[A-Z][\)\.]', "\n"+"\n".join(lines)):
                error_hint = "Looks like Multiple Choice, but check if the 'Answer:' line is correct."
            elif re.search(r'_{3,}', block):
                error_hint = "Looks like Fill-in-the-Blank, but check if 'Answer:' line is present."
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
    data = request.json
    parsed_questions = parse_quiz_text(data.get("quiz_text", ""))
    qti_package = create_qti_1_2_package(parsed_questions)
    course_id = data.get("course_id")
    access_token = data.get("access_token")

    # Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("quiz.qti.xml", qti_package.encode("utf-8"))

    zip_buffer.seek(0)
    return Response(zip_buffer.read(), mimetype="application/zip", headers={
        "Content-Disposition": "attachment; filename=quiz_package.zip"
    })
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