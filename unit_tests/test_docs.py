"""Keep the documentation honest.

The [Essay] tag was documented in the formatting guide for months while the parser turned it into
a fill-in-the-blank question, because nothing checked the docs against the code. These tests do:
the guide's examples must appear in the guide *and* parse to the type it says; the README's sample
must parse cleanly; every environment variable the code reads must be documented, and nothing
documented may be stale.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from app.utils.parser import parse_quiz_text
from app.utils.text_utils import extract_points

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


GUIDE = _read("app", "public", "Instructions.txt").replace("\r\n", "\n")
GUIDE_LINES = [line.strip() for line in GUIDE.split("\n")]
GUIDE_FLAT = re.sub(r"\s+", " ", GUIDE)   # for prose claims, which the guide wraps across lines


def _in_guide(example):
    """True if the example's lines appear, in order and contiguously, in the guide.

    Indentation is ignored, and the first line may follow a label on the same line
    ("Example: The capital of [France] is [Paris].").
    """
    wanted = [line.strip() for line in example.strip().split("\n")]
    for i in range(len(GUIDE_LINES) - len(wanted) + 1):
        window = GUIDE_LINES[i:i + len(wanted)]
        if window[0].endswith(wanted[0]) and window[1:] == wanted[1:]:
            return True
    return False


def _only(text):
    questions = parse_quiz_text(text)
    assert len(questions) == 1, questions
    return questions[0]


# --- the formatting guide's examples -----------------------------------------

GUIDE_EXAMPLES = [
    ("multiple choice",
     "Which programming language is known as the language of the web?\nA) Python\nB) JavaScript\nC) C++\nAnswer: B",
     "multiple_choice_question"),
    ("multiple answers, starred",
     "Select the prime numbers:\n*A) 2\n B) 4\n*C) 7",
     "multiple_answers_question"),
    ("multiple answers, tagged",
     "Select the prime numbers:\nA) 2\nB) 4\nC) 7\nAnswer: A, C",
     "multiple_answers_question"),
    ("true/false",
     "Water boils at 100 degrees Celsius. (1 point)\nAnswer: True",
     "true_false_question"),
    ("true/false, explicit",
     "TF: The Earth is round.\nAnswer: True",
     "true_false_question"),
    ("short answer",
     "What is the capital of France?\nAnswer: Paris",
     "short_answer_question"),
    ("short answer, explicit",
     "SA: What is the capital of France?\nAnswer: Paris",
     "short_answer_question"),
    ("single blank",
     "A ____ in time saves nine.\nAnswer: stitch",
     "short_answer_question"),
    ("fill in multiple blanks, auto",
     "The capital of [France] is [Paris].",
     "fill_in_multiple_blanks_question"),
    ("fill in multiple blanks, mapped",
     "The [c] of France is [p].\nAnswers: c: capital, p: Paris",
     "fill_in_multiple_blanks_question"),
    ("essay",
     "Essay: Discuss the socio-economic impacts of the Industrial Revolution.\nPoints: 10",
     "essay_question"),
]


@pytest.mark.parametrize("name,example,expected_type", GUIDE_EXAMPLES, ids=[e[0] for e in GUIDE_EXAMPLES])
def test_guide_example_is_in_the_guide_and_parses_to_the_documented_type(name, example, expected_type):
    assert _in_guide(example), f"the guide no longer contains this example verbatim:\n{example}"
    question = _only(example)
    assert question["type"] == expected_type, question


def test_guide_example_answers_are_what_a_reader_would_expect():
    mc = _only(GUIDE_EXAMPLES[0][1])
    assert next(a["text"] for a in mc["answers"] if a["id"] == mc["correct_answer_id"]) == "JavaScript"
    assert len(_only(GUIDE_EXAMPLES[1][1])["correct_answer_ids"]) == 2
    assert len(_only(GUIDE_EXAMPLES[2][1])["correct_answer_ids"]) == 2
    assert _only(GUIDE_EXAMPLES[3][1])["points"] == "1"
    assert _only(GUIDE_EXAMPLES[10][1])["points"] == "10"
    assert _only(GUIDE_EXAMPLES[9][1])["variables"] == {"c": ["capital"], "p": ["Paris"]}


# --- claims the guide makes in prose -----------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Q? (1 point)", "1"), ("Q? (5 pts)", "5"), ("Q? [Points: 10]", "10"), ("Q? Points: 5", "5"), ("Q? Score: 2", "2"),
])
def test_every_documented_points_format_works(text, expected):
    for fmt in ("(1 point)", '"(5 pts)"', "[Points: 10]", "Points: 5", "Score: 2"):
        assert fmt.strip('"') in GUIDE_FLAT, f"the guide should still list {fmt}"
    assert extract_points(text) == expected


def test_guide_says_plain_text_like_point_3_is_not_points():
    assert "point 3 is the vertex" in GUIDE_FLAT
    question = _only("In the graph, point 3 is the vertex. What is its x-coordinate?\nAnswer: 2")
    assert question["points"] == "1"
    assert "point 3 is the vertex" in question["question_text"]


def test_guide_says_brackets_are_fine_when_there_is_an_answer_line():
    assert "What does arr[0] return?" in GUIDE_FLAT
    assert _only("What does arr[0] return?\nAnswer: the first element")["type"] == "short_answer_question"


def test_guide_says_a_bracketed_question_with_no_answer_line_is_fill_in_multiple_blanks():
    assert _only("Describe the loop in [step one] and [step two].")["type"] == "fill_in_multiple_blanks_question"


def test_guide_says_essay_can_end_with_the_tag():
    assert 'end with "[Essay]"' in GUIDE_FLAT
    assert _only("Discuss the impact of the Industrial Revolution. [Essay]")["type"] == "essay_question"


def test_guide_says_the_short_answer_tag_works():
    assert '"[Short Answer]"' in GUIDE_FLAT
    assert _only("What is the capital of France? [Short Answer]\nAnswer: Paris")["type"] == "short_answer_question"


def test_guide_says_a_leading_number_is_ignored():
    question = _only("1) What is 2+2?\nA) 3\nB) 4\nAnswer: B")
    assert question["type"] == "multiple_choice_question"
    assert question["question_text"] == "What is 2+2?"


def test_guide_says_options_must_be_written_with_a_closing_parenthesis():
    """Documented limitation: 'A.' options are not recognised (the block is read as short answer)."""
    assert 'options written as "A)"' in GUIDE_FLAT and '"A." is not recognised' in GUIDE_FLAT
    assert _only("What is 2+2?\nA. 3\nB. 4\nAnswer: B")["type"] != "multiple_choice_question"


# --- README sample and the repo's sample file --------------------------------

SAMPLE_TYPES = [
    "multiple_choice_question", "essay_question", "true_false_question", "short_answer_question",
    "short_answer_question", "true_false_question", "multiple_choice_question", "short_answer_question",
    "essay_question", "short_answer_question",
]


def test_readme_sample_questions_all_parse_with_no_errors():
    block = re.search(r"# Sample Test Questions.*?```\n(.*?)```", _read("README.md"), re.S).group(1)
    assert [q["type"] for q in parse_quiz_text(block)] == SAMPLE_TYPES


def test_sample_file_in_tests_dir_parses_with_no_errors():
    assert [q["type"] for q in parse_quiz_text(_read("Tests", "Test.txt"))] == SAMPLE_TYPES


# --- configuration is documented, and the docs are not stale -----------------

def _env_vars_read_by_the_code():
    found = set()
    pattern = re.compile(r"""os\.(?:getenv|environ\.get)\(\s*["']([A-Z][A-Z0-9_]*)["']|os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']""")
    paths = [os.path.join(ROOT, "main.py")]
    for base, _dirs, files in os.walk(os.path.join(ROOT, "app")):
        if "assets" not in base:
            paths += [os.path.join(base, f) for f in files if f.endswith(".py")]
    for path in paths:
        for match in pattern.finditer(open(path, encoding="utf-8").read()):
            found.add(match.group(1) or match.group(2))
    return found


def _env_example_names():
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", _read(".env.example"), re.M))


def test_every_setting_the_code_reads_is_documented():
    readme_names = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", _read("README.md")))
    code = _env_vars_read_by_the_code()
    assert code, "scan found nothing: the regex is broken"
    assert not code - readme_names, f"read by the code but missing from the README table: {sorted(code - readme_names)}"
    assert not code - _env_example_names(), f"missing from .env.example: {sorted(code - _env_example_names())}"


def test_env_example_lists_no_stale_settings():
    """It used to document LTI_CLIENT_ID, SESSION_FILE_DIR and PERMANENT_SESSION_LIFETIME, which nothing read."""
    stale = _env_example_names() - _env_vars_read_by_the_code()
    assert not stale, f".env.example documents settings nothing reads: {sorted(stale)}"


# --- the READMEs only name scripts that exist --------------------------------

def test_frontend_readme_only_names_npm_scripts_that_exist():
    scripts = json.loads(_read("Frontend", "package.json"))["scripts"]
    named = set(re.findall(r"npm (?:run )?([a-z]+)", _read("Frontend", "README.md") + _read("README.md")))
    named -= {"ci", "install"}   # built-in npm commands, not scripts
    assert named <= set(scripts), f"documented but missing from package.json: {sorted(named - set(scripts))}"
