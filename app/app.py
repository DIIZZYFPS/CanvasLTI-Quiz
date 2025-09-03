from linecache import cache
from pprint import pprint
from flask import Flask, send_from_directory, render_template, Response, request
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

app = Flask(__name__, static_folder="assets", template_folder="templates")

config = {
    "DEBUG": True,
    "ENV": "development",
    "CACHE_TYPE": "simple",
    "CACHE_DEFAULT_TIMEOUT": 600,
    "SECRET_KEY": "replace-me",
    "SESSION_TYPE": "filesystem",
    "SESSION_FILE_DIR": mkdtemp(),
    "SESSION_COOKIE_NAME": "pylti1p3-flask-app-sessionid",
    "SESSION_COOKIE_HTTPONLY": True,
    "SESSION_COOKIE_SECURE": False,   # should be True in case of HTTPS usage (production)
    "SESSION_COOKIE_SAMESITE": None,  # should be 'None' in case of HTTPS usage (production)
    "DEBUG_TB_INTERCEPT_REDIRECTS": False
}
app.config.from_mapping(config)
cache = Cache(app)



# LTI

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
        raise Exception("Missing target_link_uri parameter")

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
    message_launch_data = message_launch.get_launch_data()
    pprint.pprint(message_launch_data)

    return render_template('index.html')

# Helpers

def _parse_multiple_choice(line, index):
    """Parses a multiple-choice question line."""
    # Regex to capture the question, the options, and the final answer
    pattern = re.compile(r'^(.*?)\s*([A-Z]\).*?)\s*Answer:\s*([A-Z])$', re.IGNORECASE)
    match = pattern.match(line)
    
    if not match:
        return None

    question_text = match.group(1).strip()
    options_text = match.group(2).strip()
    correct_answer_letter = match.group(3).upper()

    # Split the options block into individual options
    options = re.split(r'\s*(?=[A-Z]\))', options_text)
    
    answers = []
    correct_answer_id = None
    for i, option in enumerate(filter(None, options)):
        letter = option[0].upper()
        text = option[2:].strip()
        answer_id = f"q{index}_ans{i}"
        
        answers.append({"id": answer_id, "text": text})
        
        if letter == correct_answer_letter:
            correct_answer_id = answer_id
            
    return {
        "id": f"q{index}",
        "type": "multiple_choice_question",
        "question_text": question_text,
        "answers": answers,
        "correct_answer_id": correct_answer_id,
        "points": "1" # Default points
    }

def _parse_true_false(line, index):
    """Parses a true/false question line."""
    pattern = re.compile(r'^(.*?)\s*\((T\/F|True\/False)\)\s*Answer:\s*(True|False)\s*$', re.IGNORECASE)
    match = pattern.match(line)

    print(line)
    
    if not match:
        return None
        
    question_text = match.group(1).strip()
    correct_answer_text = match.group(3).capitalize()
    
    answers = [
        {"id": f"q{index}_ans0", "text": "True"},
        {"id": f"q{index}_ans1", "text": "False"}
    ]
    
    correct_answer_id = answers[0]['id'] if correct_answer_text == "True" else answers[1]['id']

    return {
        "id": f"q{index}",
        "type": "true_false_question",
        "question_text": question_text,
        "answers": answers,
        "correct_answer_id": correct_answer_id,
        "points": "1"
    }

def _parse_short_answer(line, index):
    """Parses a short answer question line."""
    pattern = re.compile(r'^(?:SA:\s*)?(.*?)(?:\[Short Answer\])?\s*Answer:\s*(.*)$', re.IGNORECASE)
    match = pattern.match(line.strip())
    
    if not match:
        return None
        
    question_text = match.group(1).strip()
    correct_answer = match.group(2).strip()
    
    return {
        "id": f"q{index}",
        "type": "short_answer_question",
        "question_text": question_text,
        "answers": [{"id": f"q{index}_ans0", "text": correct_answer}], # Store the correct answer(s)
        "points": "1"
    }

def _parse_essay(line, index):
    """Parses an essay question line."""
    pattern = re.compile(r'^(?:Essay:\s*)?(.*?)(?:\[Essay\])?\s*(?:Points:\s*(\d+))?$', re.IGNORECASE)
    match = pattern.match(line.strip())
    
    if not match:
        return None
        
    question_text = match.group(1).strip()
    points = match.group(2) if match.group(2) else "1" # Extract points if available

    return {
        "id": f"q{index}",
        "type": "essay_question",
        "question_text": question_text,
        "answers": [], # Essay questions have no pre-defined answers
        "points": points
    }

def _parse_fill_in_the_blank(line, index):
    """Parses a fill-in-the-blank question line."""
    pattern = re.compile(r'^(.*?)\s*_{2,}\s*(.*?)\s*Answer:\s*(.*)$', re.IGNORECASE)
    match = pattern.match(line)
    
    if not match:
        return None
        
    question_text = f"{match.group(1).strip()} _____ {match.group(2).strip()}"
    correct_answer = match.group(3).strip()

    return {
        "id": f"q{index}",
        "type": "fill_in_the_blank_question",
        "question_text": question_text,
        "answers": [{"id": f"q{index}_ans0", "text": correct_answer}],
        "points": "1"
    }

def parse_quiz_text(text_input):
    """
    Parses a multi-line string of quiz questions into a structured list of dictionaries.
    """
    questions = []
    lines = text_input.strip().split('\n')
    print(lines)
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        print("(T/F)" in line, line)

        question_data = None
        
        # The order of these checks matters. We check for the most unique patterns first.
        if "Answer:" in line and ("(T/F)" in line or "(True/False)" in line):
            question_data = _parse_true_false(line, i)
        elif "Answer:" in line and re.search(r'[A-Z]\)', line):
            question_data = _parse_multiple_choice(line, i)
        elif re.search(r'_{2,}', line):
            question_data = _parse_fill_in_the_blank(line, i)
        elif "Answer:" in line and (line.startswith("SA:") or "[Short Answer]" in line):
            question_data = _parse_short_answer(line, i)
        elif line.startswith("Essay:") or "[Essay]" in line:
            question_data = _parse_essay(line, i)
        
        # FIX: This must be inside the loop!
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

@app.route("/api/preview", methods=['POST'])
def preview():
    data = request.json
    parsed_questions = parse_quiz_text(data.get("quiz_text", ""))
    return {"questions": parsed_questions}

@app.route("/api/download", methods=['POST'])
def download():
    data = request.json
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