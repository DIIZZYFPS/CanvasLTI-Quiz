import xml.etree.ElementTree as ET
import xml.dom.minidom

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

def _create_fmb_item(section, question):
    """Builds the XML for a Fill in Multiple Blanks question."""
    item = ET.SubElement(section, 'item', {'ident': question['id'], 'title': "Question"})
    
    # Metadata (Points and Type)
    itemmetadata = ET.SubElement(item, 'itemmetadata')
    qtimetadata = ET.SubElement(itemmetadata, 'qtimetadata')
    
    points_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(points_field, 'fieldlabel').text = 'points_possible'
    ET.SubElement(points_field, 'fieldentry').text = str(float(question['points']))
    
    type_field = ET.SubElement(qtimetadata, 'qtimetadatafield')
    ET.SubElement(type_field, 'fieldlabel').text = 'question_type'
    ET.SubElement(type_field, 'fieldentry').text = 'fill_in_multiple_blanks_question'

    # Presentation
    presentation = ET.SubElement(item, 'presentation')
    material = ET.SubElement(presentation, 'material')
    ET.SubElement(material, 'mattext', {'texttype': 'text/html'}).text = f"<div><p>{question['question_text']}</p></div>"
    
    for var, answers in question['variables'].items():
        response_lid = ET.SubElement(presentation, 'response_lid', {'ident': f"response_{var}", 'rcardinality': 'Single'})
        # Presentation for variable (unseen but required)
        var_material = ET.SubElement(response_lid, 'material')
        ET.SubElement(var_material, 'mattext', {'texttype': 'text/plain'}).text = var
        render_fib = ET.SubElement(response_lid, 'render_fib')
        ET.SubElement(render_fib, 'response_label', {'ident': f"answer_{var}"})
        
    # Response Processing
    resprocessing = ET.SubElement(item, 'resprocessing')
    outcomes = ET.SubElement(resprocessing, 'outcomes')
    ET.SubElement(outcomes, 'decvar', {'maxvalue': '100', 'minvalue': '0', 'varname': 'SCORE', 'vartype': 'Decimal'})
    
    # Scoring: Logic usually requires all variables to be correct for 100% or partial credit
    # For now, we'll do simple full credit if all answers match
    respcondition = ET.SubElement(resprocessing, 'respcondition', {'continue': 'No'})
    conditionvar = ET.SubElement(respcondition, 'conditionvar')
    
    # Requirement: ALL variables must match a correct answer
    for var, answers in question['variables'].items():
        if len(answers) == 1:
            ET.SubElement(conditionvar, 'varequal', {'respident': f"response_{var}"}).text = answers[0]
        elif len(answers) > 1:
            or_node = ET.SubElement(conditionvar, 'or')
            for ans in answers:
                ET.SubElement(or_node, 'varequal', {'respident': f"response_{var}"}).text = ans
                
    ET.SubElement(respcondition, 'setvar', {'action': 'Set', 'varname': 'SCORE'}).text = '100'

    ET.SubElement(respcondition, 'setvar', {'action': 'Set', 'varname': 'SCORE'}).text = '100'

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
