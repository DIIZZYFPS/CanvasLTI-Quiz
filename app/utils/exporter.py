import html
import xml.etree.ElementTree as ET
import re
import xml.dom.minidom
from decimal import Decimal

def _stem_html(text, with_span=False):
    """Wrap question text in the HTML Canvas expects, escaping it first.

    The stem is sent as text/html, so unescaped user text is *interpreted* as
    markup: "Which tag makes a link: <a>?" loses the tag and "x < 5" can swallow
    text up to the next '>'. Escaping makes the text show exactly as typed (and
    keeps typed markup from being injected into the quiz). Answer options are
    sent as text/plain and don't need this.
    """
    inner = html.escape(text, quote=False)
    if with_span:
        inner = f"<span>{inner}</span>"
    return f"<div><p>{inner}</p></div>"

# Answer ids for short-answer / fill-in-blank items are numeric strings. They used to be
# 8000/9000 + a random number, so two exports of the same quiz differed byte-for-byte
# (untestable, undiffable) and ids could collide between items. They are now derived from
# the question's position, so they are stable and each question gets its own range.
_ANSWER_ID_BASE = 100000
_ANSWER_ID_SPAN = 1000   # max answer ids per question

def _answer_id_base(question):
    match = re.search(r'(\d+)$', str(question.get('id', '')))
    return _ANSWER_ID_BASE + (int(match.group(1)) if match else 0) * _ANSWER_ID_SPAN

def _next_answer_id(base, counter):
    if counter - base >= _ANSWER_ID_SPAN:
        raise ValueError("A question has too many answers to export.")
    return str(counter)

def _new_item(section, question, number):
    """Create the <item> element. Canvas shows `title` as the question name, so number it
    ("Question 3") rather than naming every question just "Question"."""
    return ET.SubElement(section, 'item', {'ident': question['id'], 'title': f"Question {number}"})

def _percent_shares(n):
    """Split 100 into n per-blank score shares that sum to exactly 100.00.

    The package declares SCORE on a 0-100 scale (decvar maxvalue=100; every other item type
    does `Set SCORE 100`), with the item's weight carried by points_possible. So each blank
    of a fill-in-multiple-blanks item must add its share of 100, not of the item's points.
    Shares are computed in cents so the total never drifts (3 blanks used to give
    0.33 + 0.33 + 0.33 = 0.99): the remainder goes to the last blanks (33.33, 33.33, 33.34).
    """
    if n <= 0:
        return []
    base, extra = divmod(10000, n)
    return [Decimal(base + (1 if i >= n - extra else 0)) / 100 for i in range(n)]

def _safe_var_ident(var, index):
    """Convert a FMB variable name to a safe QTI identifier.
    Replaces spaces and special characters; falls back to a positional slug."""
    slug = re.sub(r'[^A-Za-z0-9_]', '_', var).strip('_')
    if not slug:
        slug = f"var_{index}"
    return f"response_{slug}"

def _create_mcq_item(section, question, number):
    """Builds the XML for a Multiple Choice or True/False question."""
    item = _new_item(section, question, number)
    
    # Metadata (Points)
    itemmetadata = ET.SubElement(item, 'itemmetadata')
    qtimetadata = ET.SubElement(itemmetadata, 'qtimetadata')
    points_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(points_field, 'fieldlabel').text = 'points_possible'
    ET.SubElement(points_field, 'fieldentry').text = str(float(question['points']))

    # Presentation (Question Text and Answers)
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = _stem_html(question['question_text'])
    
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

def _create_essay_item(section, question, number):
    """Builds the XML for an Essay question."""
    item = _new_item(section, question, number)

    # Metadata (Points)
    itemmetadata = ET.SubElement(item, 'itemmetadata')
    qtimetadata = ET.SubElement(itemmetadata, 'qtimetadata')
    points_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(points_field, 'fieldlabel').text = 'points_possible'
    ET.SubElement(points_field, 'fieldentry').text = str(float(question['points']))

    # Presentation (Just the prompt)
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = _stem_html(question['question_text'])
    
    # Response container for text entry
    response_str = ET.SubElement(presentation, 'response_str', {'ident': 'response1', 'rcardinality': 'Single'})
    ET.SubElement(response_str, 'render_fib') # Essay questions just need this empty tag
    
    # Response processing is minimal for essays (manual grading)
    ET.SubElement(item, 'resprocessing')

def _create_short_answer_item(section, question, number):
    """Builds the XML for a Short Answer or Fill in the Blank question matching Canvas format."""
    item = _new_item(section, question, number)

    # Metadata
    itemmetadata = ET.SubElement(item, 'itemmetadata')
    qtimetadata = ET.SubElement(itemmetadata, 'qtimetadata')
    
    points_possible = float(question['points'])
    ET.SubElement(qtimetadata, 'qtimetadatafield') # spacer
    points_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(points_field, 'fieldlabel').text = 'points_possible'
    ET.SubElement(points_field, 'fieldentry').text = str(points_possible)
    
    type_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(type_field, 'fieldlabel').text = 'question_type'
    ET.SubElement(type_field, 'fieldentry').text = 'short_answer_question'

    # Generate numeric IDs for answers
    all_ans_ids = []
    ans_to_id_map = {}
    id_base = id_counter = _answer_id_base(question)
    for ans in question['answers']:
        ans_id = _next_answer_id(id_base, id_counter)
        id_counter += 1
        ans_to_id_map[ans['text']] = ans_id
        all_ans_ids.append(ans_id)

    ids_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(ids_field, 'fieldlabel').text = 'original_answer_ids'
    ET.SubElement(ids_field, 'fieldentry').text = ",".join(all_ans_ids)

    # Presentation
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = _stem_html(question['question_text'], with_span=True)
    
    response_lid = ET.SubElement(presentation, 'response_lid', {'ident': 'response1', 'rcardinality': 'Single'})
    render_choice = ET.SubElement(response_lid, 'render_choice')
    for ans in question['answers']:
        ans_id = ans_to_id_map[ans['text']]
        resp_label = ET.SubElement(render_choice, 'response_label', {'ident': ans_id})
        ans_mat = ET.SubElement(resp_label, 'material')
        ET.SubElement(ans_mat, 'mattext', {'texttype': 'text/plain'}).text = ans['text']

    # Response Processing
    resprocessing = ET.SubElement(item, 'resprocessing')
    outcomes = ET.SubElement(resprocessing, 'outcomes')
    ET.SubElement(outcomes, 'decvar', {'maxvalue': '100', 'minvalue': '0', 'varname': 'SCORE', 'vartype': 'Decimal'})
    
    respcondition = ET.SubElement(resprocessing, 'respcondition', {'continue': 'No'})
    conditionvar = ET.SubElement(respcondition, 'conditionvar')
    
    if len(question['answers']) > 1:
        or_node = ET.SubElement(conditionvar, 'or')
        for ans in question['answers']:
            ans_id = ans_to_id_map[ans['text']]
            ET.SubElement(or_node, 'varequal', {'respident': 'response1'}).text = ans_id
    else:
        ans_id = ans_to_id_map[question['answers'][0]['text']]
        ET.SubElement(conditionvar, 'varequal', {'respident': 'response1'}).text = ans_id
        
    ET.SubElement(respcondition, 'setvar', {'action': 'Set', 'varname': 'SCORE'}).text = '100'

def _create_fmb_item(section, question, number):
    """Builds the XML for a Fill in Multiple Blanks question matching Canvas format."""
    item = _new_item(section, question, number)
    
    # Metadata
    itemmetadata = ET.SubElement(item, 'itemmetadata')
    qtimetadata = ET.SubElement(itemmetadata, 'qtimetadata')
    
    points_possible = float(question['points'])
    ET.SubElement(qtimetadata, 'qtimetadatafield') # spacer
    points_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(points_field, 'fieldlabel').text = 'points_possible'
    ET.SubElement(points_field, 'fieldentry').text = str(points_possible)
    
    type_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(type_field, 'fieldlabel').text = 'question_type'
    ET.SubElement(type_field, 'fieldentry').text = 'fill_in_multiple_blanks_question'

    # Generate numeric IDs for answers for original_answer_ids metadata
    all_ans_ids = []
    var_to_id_map = {} # (var, text) -> numeric_id
    var_to_ident = {}  # var -> safe QTI ident
    id_base = id_counter = _answer_id_base(question)

    # Drop empty answer strings up front. An empty synonym can't be matched (and used to
    # raise KeyError when it sat alongside real ones); a blank left with no answers at all
    # is shown but not scored.
    variables = {var: [t for t in texts if t] for var, texts in question['variables'].items()}

    for idx, (var, text_list) in enumerate(variables.items()):
        var_to_ident[var] = _safe_var_ident(var, idx)
        for text in text_list:
            if not text: # Skip empty answers
                continue
            ans_id = _next_answer_id(id_base, id_counter)
            id_counter += 1
            var_to_id_map[(var, text)] = ans_id
            all_ans_ids.append(ans_id)

    ids_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(ids_field, 'fieldlabel').text = 'original_answer_ids'
    ET.SubElement(ids_field, 'fieldentry').text = ",".join(all_ans_ids)

    # Presentation
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    # Wrap in div spans as seen in reference
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = _stem_html(question['question_text'], with_span=True)
    
    for var, text_list in variables.items():
        var_ident = var_to_ident[var]
        response_lid = ET.SubElement(presentation, 'response_lid', {'ident': var_ident})
        var_mat = ET.SubElement(response_lid, 'material')
        ET.SubElement(var_mat, 'mattext', {'texttype': 'text/plain'}).text = var
        
        render_choice = ET.SubElement(response_lid, 'render_choice')
        for text in text_list:
            ans_id = var_to_id_map.get((var, text))
            if not ans_id:
                continue
            resp_label = ET.SubElement(render_choice, 'response_label', {'ident': ans_id})
            ans_mat = ET.SubElement(resp_label, 'material')
            ET.SubElement(ans_mat, 'mattext', {'texttype': 'text/plain'}).text = text
            
    # Response Processing
    resprocessing = ET.SubElement(item, 'resprocessing')
    outcomes = ET.SubElement(resprocessing, 'outcomes')
    ET.SubElement(outcomes, 'decvar', {'maxvalue': '100', 'minvalue': '0', 'varname': 'SCORE', 'vartype': 'Decimal'})
    
    # Each scored blank adds its share of 100 (see _percent_shares); blanks with no answers
    # can't be scored and are skipped.
    shares = dict(zip(
        [var for var, texts in variables.items() if texts],
        _percent_shares(sum(1 for texts in variables.values() if texts)),
    ))

    for var, text_list in variables.items():
        if var not in shares:
            continue
        respcondition = ET.SubElement(resprocessing, 'respcondition')
        conditionvar = ET.SubElement(respcondition, 'conditionvar')
        var_ident = var_to_ident[var]

        # If multiple synonyms, wrap in <or>
        if len(text_list) > 1:
            or_node = ET.SubElement(conditionvar, 'or')
            for text in text_list:
                ET.SubElement(or_node, 'varequal', {'respident': var_ident}).text = var_to_id_map[(var, text)]
        else:
            ET.SubElement(conditionvar, 'varequal', {'respident': var_ident}).text = var_to_id_map[(var, text_list[0])]

        ET.SubElement(respcondition, 'setvar', {'action': 'Add', 'varname': 'SCORE'}).text = f"{shares[var]:.2f}"

def _create_multi_answer_item(section, question, number):
    """Builds the XML for a Multiple Answer (Multi-select) question."""
    item = _new_item(section, question, number)
    
    # Metadata
    itemmetadata = ET.SubElement(item, 'itemmetadata')
    qtimetadata = ET.SubElement(itemmetadata, 'qtimetadata')
    
    points_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(points_field, 'fieldlabel').text = 'points_possible'
    ET.SubElement(points_field, 'fieldentry').text = str(float(question['points']))
    
    type_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(type_field, 'fieldlabel').text = 'question_type'
    ET.SubElement(type_field, 'fieldentry').text = 'multiple_answers_question'

    # Presentation
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = _stem_html(question['question_text'])
    
    response_lid = ET.SubElement(presentation, 'response_lid', {'ident': 'response1', 'rcardinality': 'Multiple'})
    render_choice = ET.SubElement(response_lid, 'render_choice')
    
    for answer in question['answers']:
        response_label = ET.SubElement(render_choice, 'response_label', {'ident': answer['id']})
        ans_material = ET.SubElement(response_label, 'material')
        ET.SubElement(ans_material, 'mattext', {'texttype': 'text/plain'}).text = answer['text']
        
    # Response Processing
    resprocessing = ET.SubElement(item, 'resprocessing')
    outcomes = ET.SubElement(resprocessing, 'outcomes')
    ET.SubElement(outcomes, 'decvar', {'maxvalue': '100', 'minvalue': '0', 'varname': 'SCORE', 'vartype': 'Decimal'})
    
    # Require EVERY correct answer to be selected
    respcondition = ET.SubElement(resprocessing, 'respcondition', {'continue': 'No'})
    conditionvar = ET.SubElement(respcondition, 'conditionvar')
    
    # Canvas expects multiple varequal tags within an <and> for MR
    and_node = ET.SubElement(conditionvar, 'and')
    for correct_id in question['correct_answer_ids']:
        ET.SubElement(and_node, 'varequal', {'respident': 'response1'}).text = correct_id
        
    # And NO incorrect answers!
    incorrect_ids = [a['id'] for a in question['answers'] if a['id'] not in question['correct_answer_ids']]
    for inc_id in incorrect_ids:
        not_node = ET.SubElement(and_node, 'not')
        ET.SubElement(not_node, 'varequal', {'respident': 'response1'}).text = inc_id

    ET.SubElement(respcondition, 'setvar', {'action': 'Set', 'varname': 'SCORE'}).text = '100'

def create_qti_1_2_package(quiz_title, parsed_data):
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
    for number, question in enumerate(parsed_data, 1):
        q_type = question.get("type")
        
        if q_type in ["multiple_choice_question", "true_false_question"]:
            _create_mcq_item(section, question, number)
        elif q_type == "short_answer_question":
            _create_short_answer_item(section, question, number)
        elif q_type == "fill_in_multiple_blanks_question":
            _create_fmb_item(section, question, number)
        elif q_type == "multiple_answers_question":
            _create_multi_answer_item(section, question, number)
        elif q_type == "essay_question":
            _create_essay_item(section, question, number)
        else:
            # Never drop a question silently: a package with fewer questions
            # than the user previewed is worse than a refused export.
            raise ValueError(f"Cannot export question of type '{q_type}'.")

    # Convert to string and return
    rough_string = ET.tostring(qti_root, xml_declaration=True, encoding='UTF-8')
    reparsed = xml.dom.minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")
