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
