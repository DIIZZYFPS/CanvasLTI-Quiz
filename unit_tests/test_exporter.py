import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from app.utils.exporter import create_qti_1_2_package
from app.utils.parser import parse_quiz_text

# One stem per exporter code path, each containing markup-looking text.
STEMS = {
    "multiple_choice": "Which is <b>bold</b> & why?\nA) x\nB) y\nAnswer: A",
    "true_false": "TF: Is <i> an italic tag & x < 5?\nAnswer: True",
    "multiple_answers": "Pick the <b> tags.\n*A) one\nB) two\n*C) three",
    "short_answer": "SA: What does <u> do? (x < 5)\nAnswer: underline",
    "essay": "Essay: Explain <script>alert(1)</script> & why.",
    "fill_in_multiple_blanks": "The [x] & <b> tag is [y].",
}


def _html_stems(xml_text):
    root = ET.fromstring(xml_text)
    return [m.text for m in root.iter("mattext") if m.get("texttype") == "text/html"]


@pytest.mark.parametrize("kind", sorted(STEMS))
def test_question_stems_are_html_escaped(kind):
    """Regression: stems were sent as text/html unescaped, so '<a>' and 'x < 5'
    in a question were interpreted as markup by Canvas."""
    questions = parse_quiz_text(STEMS[kind])
    assert len(questions) == 1 and questions[0]["type"] != "error", questions
    stems = _html_stems(create_qti_1_2_package("T", questions))
    assert len(stems) == 1

    # Strip the fixed wrapper elements; nothing from the user's text may remain
    # as a real tag.
    body = re.sub(r"</?(?:div|p|span)>", "", stems[0])
    assert "<" not in body and ">" not in body, stems[0]
    assert "&lt;" in body


def test_escaped_stem_round_trips_to_original_text():
    import html
    questions = parse_quiz_text("Which tag makes a link: <a> or <b>? Is x < 5 && y > 3?\nA) <a>\nB) <b>\nAnswer: A")
    stem = _html_stems(create_qti_1_2_package("T", questions))[0]
    text = html.unescape(re.sub(r"</?(?:div|p|span)>", "", stem))
    assert text == "Which tag makes a link: <a> or <b>? Is x < 5 && y > 3?"


def test_plain_stem_is_unchanged():
    questions = parse_quiz_text("What is 2+2?\nA) 3\nB) 4\nAnswer: B")
    assert _html_stems(create_qti_1_2_package("T", questions)) == ["<div><p>What is 2+2?</p></div>"]


def test_title_is_preserved_verbatim_in_package():
    questions = parse_quiz_text("What year?\nAnswer: 1945")
    title = "Bob's Quiz: Week 3 – Intro / Review"
    root = ET.fromstring(create_qti_1_2_package(title, questions))
    assert root.find("assessment").get("title") == title
