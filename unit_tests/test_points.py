import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from app.utils.parser import parse_quiz_text
from app.utils.text_utils import _clean_points_text, extract_points

PROSE = [
    "In the graph, point 3 is the vertex.",
    "What is the score 5 times 2?",
    "Find the slope at point 3",
    "Points 3 and 4 lie on the line.",
    "The pts 4 and 5 are collinear.",
    "Which statement about score 10 is true?",
    "Mark point 2 on the number line.",
]


@pytest.mark.parametrize("text", PROSE)
def test_ordinary_prose_is_not_points(text):
    """Regression: a bare 'point 3' / 'score 5' was read as a point value AND deleted
    from the question text ('In the graph, point 3 is the vertex.' became 'In the graph,
    is the vertex.')."""
    assert extract_points(text) == "1"
    assert _clean_points_text(text) == text


@pytest.mark.parametrize("text,expected", [
    ("What is 2+2? (1 point)", "1"),
    ("What is 2+2? (5 pts)", "5"),
    ("What is 2+2? (10 points)", "10"),
    ("What is 2+2? (2.5 points)", "2.5"),
    ("What is 2+2? [Points: 10]", "10"),
    ("What is 2+2? (Score 5)", "5"),
    ("What is 2+2? [pts 3]", "3"),
    ("What is 2+2? Points: 5", "5"),
    ("What is 2+2? Score: 2", "2"),
    ("What is 2+2? points:7", "7"),
    ("What is 2+2? Points: .5", ".5"),
    ("Points: 4\nWhat is 2+2?", "4"),
])
def test_documented_formats_still_work(text, expected):
    assert extract_points(text) == expected


def test_default_when_unspecified():
    assert extract_points("What is 2+2?") == "1"
    assert extract_points("What is 2+2?", default="0") == "0"


def test_bare_marker_alone_on_its_own_line_is_still_honoured():
    """Legacy Respondus-style 'point 2' on its own line (see unit_tests/verify_respondus.py)."""
    block = "1. What is the capital of France?\n*a) Paris\nb) London\nc) Berlin\npoint 2"
    assert extract_points(block) == "2"
    assert extract_points("What is 2+2?\n  Score 3  \nA) 3") == "3"


def test_the_same_marker_in_prose_is_not_honoured():
    assert extract_points("What is the capital of France? point 2") == "1"


@pytest.mark.parametrize("text,expected", [
    ("What is 2+2? (1 point)", "What is 2+2?"),
    ("What is 2+2? [Points: 10]", "What is 2+2?"),
    ("What is 2+2? Points: 5", "What is 2+2?"),
    ("What is 2+2? Score: 2", "What is 2+2?"),
    ("(3 pts) What is 2+2?", "What is 2+2?"),
])
def test_clean_removes_exactly_the_marker(text, expected):
    assert _clean_points_text(text) == expected


@pytest.mark.parametrize("text", [
    "What is 2+2? (1 point)", "Essay: Explain.\nPoints: 10", "In the graph, point 3 is the vertex.",
    "Plain question", "x [Points: 4] y", "Score: 2 and then point 5",
])
def test_extraction_and_cleaning_always_agree(text):
    """What is read as points is exactly what is removed from the text (one shared pattern)."""
    states_points = extract_points(text, default=None) is not None
    changed = _clean_points_text(text) != text.strip()
    assert states_points == changed


def test_end_to_end_prose_with_point_is_left_intact():
    q = parse_quiz_text("In the graph, point 3 is the vertex. What is its x-coordinate?\nAnswer: 2")[0]
    assert q["type"] == "short_answer_question"
    assert q["points"] == "1"
    assert q["question_text"] == "In the graph, point 3 is the vertex. What is its x-coordinate?"


def test_end_to_end_documented_points_still_set_points_and_are_stripped():
    q = parse_quiz_text("In the graph, point 3 is the vertex. What is its x-coordinate? (4 points)\nAnswer: 2")[0]
    assert q["points"] == "4"
    assert q["question_text"] == "In the graph, point 3 is the vertex. What is its x-coordinate?"


def test_respondus_legacy_sample_keeps_its_points():
    text = "1. What is the capital of France?\n*a) Paris\nb) London\nc) Berlin\npoint 2"
    assert parse_quiz_text(text)[0]["points"] == "2"


def test_large_inputs_stay_fast():
    import time
    for payload in ("(" * 200_000, "( " * 100_000, "Points " * 100_000, "Points: " + "1" * 100_000 + "x", "\n".join(["Score"] * 50_000)):
        start = time.perf_counter()
        extract_points(payload)
        _clean_points_text(payload)
        assert time.perf_counter() - start < 2.0
