import re
from .text_utils import extract_points, _clean_points_text
from .respondus_parser import (
    detect_respondus_format, 
    parse_respondus_mcq, 
    parse_respondus_tf, 
    parse_respondus_essay,
    parse_respondus_fib,
    parse_respondus_fmb,
    parse_respondus_mr
)

# --- Core Branch Parsers ---

def _parse_multiple_choice(lines, index):
    """Parses a multiple-choice or multiple-answers question."""
    full_text = " ".join(lines)
    points = extract_points(full_text)
    
    # 1. Extract Answer(s) via "Answer:" or "Answers:" tag
    # Support "Answer: A" or "Answers: A, B"
    answer_match = re.search(r'Answers?:\s*([A-Z, ]+)', full_text, re.IGNORECASE)
    correct_chars = []
    if answer_match:
        # Split by comma or space and clean up
        raw_ans = answer_match.group(1).upper()
        correct_chars = [c.strip() for c in re.split(r'[, ]+', raw_ans) if c.strip()]

    # 2. Extract Options (Detect multiple * markers for parity with Respondus)
    options = []
    starred_chars = []
    for line in lines:
        match = re.match(r'^(\*?)([A-Z])[\)\.]\s*(.*)', line.strip(), re.IGNORECASE)
        if match:
            is_starred = bool(match.group(1))
            char = match.group(2).upper()
            text = match.group(3).strip()
            options.append({"id": char, "text": text})
            if is_starred:
                starred_chars.append(char)
    
    # Consolidate correct characters from both "Answers:" tag and "*" markers
    final_correct_chars = list(set(correct_chars + starred_chars))
    
    if len(options) < 2:
        return {"id": f"error_{index}", "type": "error", "question_text": full_text, "error": "Insufficient options found. List at least two options starting with 'A)', 'B)', etc."}

    # Identify question text (before first option)
    question_lines = []
    for line in lines:
        if re.match(r'^\*?[A-Z][\)\.]', line.strip(), re.IGNORECASE):
            break
        question_lines.append(line)
    
    question_text = " ".join(question_lines).strip()
    question_text = _clean_points_text(question_text)

    if not question_text:
        return {"id": f"error_{index}", "type": "error", "question_text": full_text, "error": "Question text is missing."}

    # Map to internal answer IDs
    answers = []
    correct_answer_ids = []
    for i, opt in enumerate(options):
        ans_id = f"q{index}_ans{i}"
        answers.append({"id": ans_id, "text": opt['text']})
        if opt['id'] in final_correct_chars:
            correct_answer_ids.append(ans_id)
            
    if not correct_answer_ids:
        return {"id": f"error_{index}", "type": "error", "question_text": question_text, "error": "No correct answer specified. Use 'Answer: A' or mark choices with '*'."}

    # Decide type based on number of correct answers
    if len(correct_answer_ids) > 1:
        return {
            "id": f"q{index}", 
            "type": "multiple_answers_question", 
            "question_text": question_text,
            "answers": answers, 
            "correct_answer_ids": correct_answer_ids,
            "points": points
        }
    else:
        return {
            "id": f"q{index}", 
            "type": "multiple_choice_question", 
            "question_text": question_text,
            "answers": answers, 
            "correct_answer_id": correct_answer_ids[0],
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
        "type": "short_answer_question", 
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

def _parse_core_fmb(line, index):
    """
    Parses a Core-style Fill-in-Multiple-Blanks.
    Syntax: The [a] is [b]. a: red, b: blue
    """
    points = extract_points(line)
    
    # Split question from answers
    # Use a separator like ":" or "Answers:"
    parts = re.split(r'Answers?:', line, flags=re.IGNORECASE)
    if len(parts) < 2:
        # Try finding key: value pairs directly
        question_text = line
        kv_pairs = []
    else:
        question_text = parts[0].strip()
        kv_pairs = [p.strip() for p in parts[1].split(',') if p.strip()]

    question_text = _clean_points_text(question_text)
    
    # Extract variables
    variables = re.findall(r'\[([^\]]+)\]', question_text)
    if not variables:
        return None # Not an FMB

    answer_map = {}
    if len(parts) >= 2:
        # User provided an "Answers:" line, use it for mapping
        for pair in kv_pairs:
            if ':' in pair:
                key, val = pair.split(':', 1)
                answer_map[key.strip().lower()] = [val.strip()]
    else:
        # AUTO-BLANK: Use the words inside the brackets as the answers
        for var in variables:
            answer_map[var.lower()] = [var]
    
    # Build answers and validate
    answers = {}
    missing_vars = []
    for var in variables:
        ans_list = answer_map.get(var.lower(), [])
        if not ans_list:
            missing_vars.append(var)
        answers[var] = ans_list

    if missing_vars:
        return {
            "id": f"error_{index}",
            "type": "error",
            "question_text": question_text,
            "error": f"Missing answers for bracketed variables: {', '.join(missing_vars)}. Each variable like [blank] must have a matching 'blank: answer' in the Answers section."
        }

    return {
        "id": f"q{index}",
        "type": "fill_in_multiple_blanks_question",
        "question_text": question_text,
        "variables": answers,
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
        
        is_respondus = detect_respondus_format(block)
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        points = extract_points(block)

        if is_respondus:
            print(f"Parsing block {i} as Respondus Format")
            # Detect subtype
            type_match = re.search(r'^Type:\s*([A-Z]+)', block, re.IGNORECASE | re.MULTILINE)
            r_type = type_match.group(1).upper() if type_match else "MC"
            
            # Legacy T/F check (not strictly 'Type: TF' but just *True/*False)
            if r_type == "MC" and re.search(r'^\s*\*(True|False|T|F)\s*$', block, re.IGNORECASE | re.MULTILINE):
                r_type = "TF"

            # Pre-clean lines for Respondus: remove Type: and Points: and numbering
            clean_lines = []
            for line in lines:
                l = line.strip()
                if re.match(r'^(Type|Points):', l, re.IGNORECASE):
                    continue
                if re.match(r'^\d+[\.\)]\s+', l):
                    l = re.sub(r'^\d+[\.\)]\s+', '', l)
                clean_lines.append(l)

            if r_type == "MC":
                question_data = parse_respondus_mcq(clean_lines, i, points)
            elif r_type == "TF":
                question_data = parse_respondus_tf(clean_lines, i, points)
            elif r_type in ["E", "ESSAY"]:
                question_data = parse_respondus_essay(clean_lines, i, points)
            elif r_type == "F":
                question_data = parse_respondus_fib(clean_lines, i, points)
            elif r_type == "FMB":
                question_data = parse_respondus_fmb(clean_lines, i, points)
            elif r_type == "MR":
                question_data = parse_respondus_mr(clean_lines, i, points)
            else:
                question_data = {"id": f"error_{i}", "type": "error", "question_text": block, "error": f"Unsupported Respondus type: {r_type}"}
        else:
            # Fallback to Core Branch
            print(f"Parsing block {i} as Core Format")
            full_block_text = " ".join(lines)
            full_lower = full_block_text.lower()
            
            # (Existing Router Logic)
            if re.match(r'^\d+[\.\)]\s+', lines[0]):
                lines[0] = re.sub(r'^\d+[\.\)]\s+', '', lines[0])
                full_block_text = " ".join(lines)
                full_lower = full_block_text.lower()
            
            # Check for Multiple Blanks first (Core)
            fmb_data = _parse_core_fmb(full_block_text, i)
            if fmb_data:
                question_data = fmb_data
            elif full_lower.startswith("tf:") or full_lower.startswith("true/false:"):
                question_data = _parse_true_false(lines, i)
            elif full_lower.startswith("sa:") or "[short answer]" in full_lower:
                question_data = _parse_short_answer(full_block_text, i)
            elif full_lower.startswith("essay:") or "[essay]" in full_lower:
                question_data = _parse_essay(full_block_text, i)
            elif re.search(r'_{2,}', full_block_text) and "answer:" in full_lower:
                question_data = _parse_fill_in_the_blank(full_block_text, i)
            elif "answer:" in full_lower and re.search(r'\n\s*[A-Z]\)', "\n"+"\n".join(lines), re.IGNORECASE):
                question_data = _parse_multiple_choice(lines, i)
            elif "answer:" in full_lower and re.search(r'\((T/F|True/False)\)', full_block_text, re.IGNORECASE):
                question_data = _parse_true_false(lines, i)
            else:
                error_hint = "Format not recognized."
                if re.search(r'\n[A-Z][\)\.]', "\n"+"\n".join(lines), re.IGNORECASE):
                    error_hint = "Looks like Multiple Choice, but check if the 'Answer:' line is correct."
                elif re.search(r'_{1,}', block):
                    error_hint = "Looks like Fill-in-the-Blank, but check if 'Answer:' line is present."
                elif "True" in block or "False" in block:
                    error_hint = "Looks like True/False. Ensure it ends with 'Answer: True' or 'Answer: False'."

                question_data = {
                    "id": f"error_{i}",
                    "type": "error",
                    "question_text": block,
                    "error": f"{error_hint} Please refer to the formatting guide.",
                }
        
        if question_data:
            questions.append(question_data)
            
    return questions
