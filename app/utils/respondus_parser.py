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
    """Parses Respondus-style Multiple Choice/Multiple Response questions."""
    options = []
    correct_ids = []
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
                correct_ids.append(ans_id)
        elif not found_options:
            question_lines.append(line)
            
    question_text = " ".join(question_lines).strip()
    question_text = _clean_points_text(question_text)
    
    if not options or not correct_ids:
        return {"id": f"error_{i}", "type": "error", "question_text": " ".join(lines), "error": "Invalid Respondus MCQ format. Ensure at least one correct answer is marked with *."}

    if len(correct_ids) > 1:
        return {
            "id": f"q{i}", 
            "type": "multiple_answers_question", 
            "question_text": question_text,
            "answers": options, 
            "correct_answer_ids": correct_ids,
            "points": points
        }
    else:
        return {
            "id": f"q{i}", 
            "type": "multiple_choice_question", 
            "question_text": question_text,
            "answers": options, 
            "correct_answer_id": correct_ids[0], 
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

def parse_respondus_fib(lines, i, points):
    """
    Parses Respondus-style Fill-in-the-blank (Short Answer).
    Type: F
    Supports multiple acceptable correct answers.
    """
    answers = []
    question_lines = []
    
    # First line might be question, or Type: F
    for line in lines:
        l = line.strip()
        # Option markers like a. or 1.
        opt_match = re.match(r'^[a-z0-9][\.\)]\s*(.*)', l, re.IGNORECASE)
        if opt_match:
            answers.append({"id": f"q{i}_ans{len(answers)}", "text": opt_match.group(1).strip()})
        else:
            question_lines.append(l)
            
    question_text = _clean_points_text(" ".join(question_lines).strip())
    
    if not answers:
        return {"id": f"error_{i}", "type": "error", "question_text": question_text, "error": "No answers found for Short Answer question. List them as 'a. Answer'."}

    return {
        "id": f"q{i}",
        "type": "short_answer_question",
        "question_text": question_text,
        "answers": answers,
        "points": points
    }

def parse_respondus_fmb(lines, i, points):
    """
    Parses Respondus-style Fill-in-Multiple-Blanks.
    Type: FMB
    Text: [a] is red.
    a = Roses
    """
    question_lines = []
    answer_map = {} # variable -> list of answers
    
    for line in lines:
        l = line.strip()
        # Look for var = value
        match = re.match(r'^([^=]+)\s*=\s*(.*)', l)
        if match:
            var = match.group(1).strip().lower()
            val = match.group(2).strip()
            if var not in answer_map:
                answer_map[var] = []
            answer_map[var].append(val)
        else:
            question_lines.append(l)
            
    question_text = _clean_points_text(" ".join(question_lines).strip())
    
    # Extract variables from brackets in text
    variables = re.findall(r'\[([^\]]+)\]', question_text)
    if not variables:
        return {"id": f"error_{i}", "type": "error", "question_text": question_text, "error": "No bracketed variables found in FMB question (e.g. [color])."}
    
    # Build answers structure and validate
    answers = {}
    missing_vars = []
    for var in variables:
        v_lower = var.lower()
        if v_lower in answer_map:
            answers[var] = answer_map[v_lower]
        else:
            missing_vars.append(var)

    if missing_vars:
        return {
            "id": f"error_{i}",
            "type": "error",
            "question_text": question_text,
            "error": f"Missing definitions for bracketed variables: {', '.join(missing_vars)}. Each variable like [blank] must have a matching 'blank = answer' line."
        }

    return {
        "id": f"q{i}",
        "type": "fill_in_multiple_blanks_question",
        "question_text": question_text,
        "variables": answers, 
        "points": points
    }

def parse_respondus_mr(lines, i, points):
    """
    Parses Respondus-style Multiple Response (Multi-select).
    Type: MR
    Correct answers marked with *.
    """
    options = []
    correct_ids = []
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
                correct_ids.append(ans_id)
        elif not found_options:
            question_lines.append(line)
            
    question_text = _clean_points_text(" ".join(question_lines).strip())
    
    if not options or not correct_ids:
        return {"id": f"error_{i}", "type": "error", "question_text": " ".join(lines), "error": "Invalid Respondus MR format. Ensure correct answers are marked with *."}

    return {
        "id": f"q{i}", 
        "type": "multiple_answers_question", 
        "question_text": question_text,
        "answers": options, 
        "correct_answer_ids": correct_ids, # Note: plural
        "points": points
    }
