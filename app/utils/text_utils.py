import re

# Lines that continue the current question block rather than starting a new
# one: lettered options (A)/*A)/a.), Answer(s): lines, Respondus Type:/Points:
# metadata, and FMB "var = value" answer lines.
_DOCX_CONTINUATION_RE = re.compile(
    r'^('
    r'\*?[A-Za-z][\.\)]\s+'
    r'|Answers?:'
    r'|Type:\s*[A-Za-z]+'
    r'|Points?:'
    r'|[^=\n]{1,40}=\s*\S'
    r')',
    re.IGNORECASE,
)

# Respondus metadata lines (Type: MC / Points: 5) precede the actual
# question text/options, so the paragraph immediately following one must
# stay attached to the same block even though it doesn't itself look like
# a continuation (e.g. plain question text right after "Type: MC").
_DOCX_METADATA_RE = re.compile(r'^(Type|Points?):', re.IGNORECASE)

def join_docx_paragraphs(paragraphs):
    """
    Join DOCX paragraph text into a parser-ready block, inserting a blank
    line before any paragraph that starts a new question.

    Word documents rarely contain an actual empty paragraph between
    questions - the visual gap comes from paragraph spacing/styling instead.
    Joining paragraphs with a single newline (as plain paragraph.text would)
    collapses every question into one giant block, since parse_quiz_text
    splits on blank lines. This reconstructs those separators by treating
    any paragraph that isn't an option/answer/metadata continuation as the
    start of a new question.
    """
    out = []
    prev_was_content = False
    prev_was_metadata = False
    for raw in paragraphs:
        line = raw.strip()
        if not line:
            out.append('')
            prev_was_content = False
            prev_was_metadata = False
            continue
        if prev_was_content and not prev_was_metadata and not _DOCX_CONTINUATION_RE.match(line):
            out.append('')
        out.append(line)
        prev_was_content = True
        prev_was_metadata = bool(_DOCX_METADATA_RE.match(line))
    return "\n".join(out)

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
