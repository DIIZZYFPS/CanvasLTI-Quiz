import re

def extract_points(text, default="1"):
    """
    Extracts points from a string in various formats:
    - (10 points), (5 pts)
    - Points: 10, Score: 10
    Returns the points as a string, e.g., "10".
    """
    pattern = re.compile(
        r'(?:'
        r'[\(\[]\s*\b(?:Points?|Score|Pts?)\b:?\s*(?P<label_bracketed>\d*\.?\d+)\s*[\)\]]'  # [Points: 10], (Score 5)
        r'|'
        r'\b(?:Points?|Score|Pts?)\b:?\s*(?P<label>\d*\.?\d+)'                              # Points: 10
        r'|'
        r'\(\s*(?P<numeric_first>\d*\.?\d+)\s*(?:points?|pts?)\s*\)'                        # (10 points), (5 pts)
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
        r'[\(\[]\s*\b(?:Points?|Score|Pts?)\b:?\s*\d*\.?\d+\s*[\)\]]'   # [Points: 10], (Score 5)
        r'|'
        r'\b(?:Points?|Score|Pts?)\b:?\s*\d*\.?\d+'                    # Points: 10
        r'|'
        r'\(\s*\d*\.?\d+\s*(?:points?|pts?)\s*\)'                      # (10 points), (5 pts)
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
