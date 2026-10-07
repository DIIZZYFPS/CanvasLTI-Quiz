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

# A bracketed fill-in-the-blank variable, e.g. "[color]". The body excludes '['
# on purpose: with the naive `\[([^\]]+)\]`, a run like "[[[[[..." made every '['
# rescan to the end of the input before failing, which is quadratic - a 40 KB
# paste took seconds of CPU on an unauthenticated endpoint. Excluding '[' makes
# each scan stop at the next '[', so matching is linear.
BLANK_VAR_RE = re.compile(r'\[([^\[\]]+)\]')

# The single definition of "this text states a point value". Both extract_points() and
# _clean_points_text() use it, so what is read as points is exactly what is removed from
# the question text (they used to be two copies that could drift apart).
#
# A bare "Points/Score/Pts" word is only a marker when it is unmistakable - with a colon,
# inside brackets, in "(N points)" form, or alone on its own line. Without that, ordinary
# prose such as "point 3 is the vertex" was both read as points and deleted from the question.
_POINTS_RE = re.compile(
    r'(?:'
    r'[\(\[]\s*\b(?:Points?|Score|Pts?)\b:?\s*(?P<bracketed>\d*\.?\d+)\s*[\)\]]'   # [Points: 10], (Score 5)
    r'|'
    r'\(\s*(?P<numeric_first>\d*\.?\d+)\s*(?:points?|pts?)\s*\)'                    # (10 points), (5 pts)
    r'|'
    r'\b(?:Points?|Score|Pts?)\b\s*:\s*(?P<labelled>\d*\.?\d+)'                      # Points: 10, Score: 2
    r'|'
    r'^[ \t]*(?:Points?|Score|Pts?)[ \t]+(?P<own_line>\d*\.?\d+)[ \t]*$'             # "point 2" alone on a line
    r')',
    re.IGNORECASE | re.MULTILINE,
)

def extract_points(text, default="1"):
    """
    Extracts points from a string in various formats:
    - (10 points), (5 pts)
    - [Points: 10], (Score 5)
    - Points: 10, Score: 10
    - "point 2" on a line of its own
    Returns the points as a string, e.g., "10".
    """
    match = _POINTS_RE.search(text)
    if match:
        for group_name in ("bracketed", "numeric_first", "labelled", "own_line"):
            value = match.group(group_name)
            if value is not None:
                return value
    return default

def _clean_points_text(text):
    """Removes the points string from the question text to clean it up."""
    return _POINTS_RE.sub('', text).strip()
