import re
from .text_utils import extract_points, _clean_points_text

def detect_respondus_format(text):
    """
    Heuristic to detect if a block of text follows Respondus Standard Format.
    Look for '*A' or '*1' or 'Type: [letter]'.
    """
    if re.search(r'^\s*\*?[A-Z][\.\)]\s+', text, re.IGNORECASE | re.MULTILINE):
        # If we see *A) or *a., it's definitely respondus
        if re.search(r'^\s*\*[A-Z][\.\)]\s+', text, re.IGNORECASE | re.MULTILINE):
            return True
    
    # Check for Respondus True/False marker *True or *False
    if re.search(r'^\s*\*(True|False|T|F)\s*$', text, re.IGNORECASE | re.MULTILINE):
        return True
        
    if re.search(r'^Type:\s*[A-Z]{1,3}', text, re.IGNORECASE | re.MULTILINE):
        return True
    return False

def parse_respondus_mcq(lines, i, points):
    """Parses Respondus-style Multiple Choice questions."""
    options = []
    correct_answer_id = None
    question_lines = []
    
    found_options = False
    for line in lines:
        # Match *A) text or A) text
        opt_match = re.match(r'^(\*?)([A-Z])[\.\)]\s*(.*)', line.strip(), re.IGNORECASE)
        if opt_match:
            found_options = True
            is_correct = bool(opt_match.group(1))
            opt_text = opt_match.group(3).strip()
            
            ans_id = f"q{i}_ans{len(options)}"
            options.append({"id": ans_id, "text": opt_text})
            if is_correct:
                correct_answer_id = ans_id
        elif not found_options:
            question_lines.append(line)
            
    question_text = " ".join(question_lines).strip()
    question_text = _clean_points_text(question_text)
    
    if not options or not correct_answer_id:
        return {"id": f"error_{i}", "type": "error", "question_text": " ".join(lines), "error": "Invalid Respondus MCQ format. Ensure correct answer is marked with *."}

    return {
        "id": f"q{i}", 
        "type": "multiple_choice_question", 
        "question_text": question_text,
        "answers": options, 
        "correct_answer_id": correct_answer_id, 
        "points": points
    }

def parse_respondus_tf(lines, i, points):
    """Parses Respondus-style True/False questions."""
    question_lines = []
    correct_is_true = None
    
    for line in lines:
        clean = line.strip().lower()
        if clean in ["*true", "*t"]:
            correct_is_true = True
        elif clean in ["*false", "*f"]:
            correct_is_true = False
        elif clean not in ["true", "false", "t", "f"]:
            question_lines.append(line)
            
    if correct_is_true is None:
        return {"id": f"error_{i}", "type": "error", "question_text": " ".join(lines), "error": "Could not find correct answer for Respondus T/F. Mark with '*'."}

    question_text = _clean_points_text(" ".join(question_lines).strip())
    answers = [{"id": f"q{i}_ans0", "text": "True"}, {"id": f"q{i}_ans1", "text": "False"}]
    correct_id = answers[0]['id'] if correct_is_true else answers[1]['id']

    return {
        "id": f"q{i}", 
        "type": "true_false_question", 
        "question_text": question_text,
        "answers": answers, 
        "correct_answer_id": correct_id, 
        "points": points
    }

def parse_respondus_essay(lines, i, points):
    """Parses Respondus-style Essay questions."""
    clean_lines = [l for l in lines if not re.match(r'^Type:\s*(E|ESSAY)', l, re.IGNORECASE)]
    question_text = _clean_points_text(" ".join(clean_lines).strip())
    
    return {
        "id": f"q{i}",
        "type": "essay_question",
        "question_text": question_text,
        "answers": [], 
        "points": points
    }
