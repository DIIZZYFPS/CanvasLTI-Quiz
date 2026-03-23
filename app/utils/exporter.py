import xml.etree.ElementTree as ET
import re
import random
import xml.dom.minidom

def _safe_var_ident(var, index):
    """Convert a FMB variable name to a safe QTI identifier.
    Replaces spaces and special characters; falls back to a positional slug."""
    slug = re.sub(r'[^A-Za-z0-9_]', '_', var).strip('_')
    if not slug:
        slug = f"var_{index}"
    return f"response_{slug}"

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
    """Builds the XML for a Short Answer or Fill in the Blank question matching Canvas format."""
    item = ET.SubElement(section, 'item', {'ident': question['id'], 'title': "Question"})

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
    id_counter = 8000 + random.randint(100, 999)
    for ans in question['answers']:
        ans_id = str(id_counter)
        id_counter += 1
        ans_to_id_map[ans['text']] = ans_id
        all_ans_ids.append(ans_id)

    ids_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(ids_field, 'fieldlabel').text = 'original_answer_ids'
    ET.SubElement(ids_field, 'fieldentry').text = ",".join(all_ans_ids)

    # Presentation
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = f"<div><p><span>{question['question_text']}</span></p></div>"
    
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

def _create_fmb_item(section, question):
    """Builds the XML for a Fill in Multiple Blanks question matching Canvas format."""
    item = ET.SubElement(section, 'item', {'ident': question['id'], 'title': "Question"})
    
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
    id_counter = 9000 + random.randint(100, 999)

    for idx, (var, text_list) in enumerate(question['variables'].items()):
        var_to_ident[var] = _safe_var_ident(var, idx)
        for text in text_list:
            if not text: # Skip empty answers
                continue
            ans_id = str(id_counter)
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
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = f"<div><p><span>{question['question_text']}</span></p></div>"
    
    for var, text_list in question['variables'].items():
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
    
    # Calculate point split
    num_vars = len(question['variables'])
    points_per_blank = points_possible / num_vars if num_vars > 0 else 0
    
    for var, text_list in question['variables'].items():
        respcondition = ET.SubElement(resprocessing, 'respcondition')
        conditionvar = ET.SubElement(respcondition, 'conditionvar')
        var_ident = var_to_ident[var]
        
        # If multiple synonyms, wrap in <or>
        if len(text_list) > 1:
            or_node = ET.SubElement(conditionvar, 'or')
            for text in text_list:
                ans_id = var_to_id_map[(var, text)]
                ET.SubElement(or_node, 'varequal', {'respident': var_ident}).text = ans_id
        else:
            if not text_list:
                # Should not happen with new parser validation, but safe-guard
                continue
            ans_id = var_to_id_map.get((var, text_list[0]))
            if ans_id:
                ET.SubElement(conditionvar, 'varequal', {'respident': var_ident}).text = ans_id
            
        ET.SubElement(respcondition, 'setvar', {'action': 'Add', 'varname': 'SCORE'}).text = f"{points_per_blank:.2f}"

def _create_multi_answer_item(section, question):
    """Builds the XML for a Multiple Answer (Multi-select) question."""
    item = ET.SubElement(section, 'item', {'ident': question['id'], 'title': "Question"})
    
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
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = f"<div><p>{question['question_text']}</p></div>"
    
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
    for question in parsed_data:
        q_type = question.get("type")
        
        if q_type in ["multiple_choice_question", "true_false_question"]:
            _create_mcq_item(section, question)
        elif q_type == "short_answer_question":
            _create_short_answer_item(section, question)
        elif q_type == "fill_in_multiple_blanks_question":
            _create_fmb_item(section, question)
        elif q_type == "multiple_answers_question":
            _create_multi_answer_item(section, question)
        elif q_type == "essay_question":
            _create_essay_item(section, question)
        else:
            print(f"Warning: Unknown question type '{q_type}' - skipping.")

    # Convert to string and return
    rough_string = ET.tostring(qti_root, xml_declaration=True, encoding='UTF-8')
    reparsed = xml.dom.minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")
