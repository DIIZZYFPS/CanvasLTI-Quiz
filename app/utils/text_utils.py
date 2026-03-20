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
