import os
import re
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal

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


# --- deterministic output ----------------------------------------------------

MIXED_QUIZ = (
    "What is 2+2?\nA) 3\nB) 4\nAnswer: B\n\n"
    "SA: Capital of France?\nAnswer: Paris\n\n"
    "The [a] and [b] are blanks.\nAnswers: a: x, b: y\n\n"
    "SA: Largest planet?\nAnswer: Jupiter\n\n"
    "Essay: Discuss."
)


def _export(text):
    questions = parse_quiz_text(text)
    assert all(q["type"] != "error" for q in questions), questions
    return create_qti_1_2_package("T", questions)


def test_export_is_byte_for_byte_deterministic():
    """Regression: answer ids used a random component, so exporting the same quiz twice
    gave different files (impossible to snapshot-test or diff)."""
    assert _export(MIXED_QUIZ) == _export(MIXED_QUIZ)


def _answer_ids(xml_text):
    root = ET.fromstring(xml_text)
    ids = []
    for item in root.iter("item"):
        field = next((f for f in item.iter("qtimetadatafield")
                      if f.findtext("fieldlabel") == "original_answer_ids"), None)
        if field is not None and field.findtext("fieldentry"):
            ids.append((item.get("ident"), field.findtext("fieldentry").split(",")))
    return ids


def test_answer_ids_are_numeric_and_unique_across_items():
    ids = _answer_ids(_export(MIXED_QUIZ))
    flat = [i for _, group in ids for i in group]
    assert len(ids) == 3                       # two short-answers and the blanks question
    assert all(i.isdigit() for i in flat)
    assert len(flat) == len(set(flat)), "answer ids collided between questions"


def test_a_questions_ids_do_not_depend_on_what_follows_it():
    first_only = dict(_answer_ids(_export("SA: Capital of France?\nAnswer: Paris")))
    with_more = dict(_answer_ids(_export("SA: Capital of France?\nAnswer: Paris\n\nSA: Largest planet?\nAnswer: Jupiter")))
    assert first_only["q0"] == with_more["q0"]


def test_every_response_ident_matches_a_declared_answer_id():
    xml_text = _export(MIXED_QUIZ)
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        labels = {lbl.get("ident") for lbl in item.iter("response_label")}
        for cond in item.iter("varequal"):
            assert cond.text in labels, (item.get("ident"), cond.text, labels)


# --- item titles -------------------------------------------------------------

def test_items_are_titled_with_their_position():
    root = ET.fromstring(_export(MIXED_QUIZ))
    assert [i.get("title") for i in root.iter("item")] == [f"Question {n}" for n in range(1, 6)]


# --- fill-in-multiple-blanks scoring -----------------------------------------

def _fmb_scores(xml_text):
    root = ET.fromstring(xml_text)
    return [Decimal(s.text) for s in root.iter("setvar") if s.get("action") == "Add"]


@pytest.mark.parametrize("blanks,expected", [
    (1, ["100.00"]),
    (2, ["50.00", "50.00"]),
    (3, ["33.33", "33.33", "33.34"]),
    (4, ["25.00"] * 4),
    (6, ["16.66", "16.66", "16.67", "16.67", "16.67", "16.67"]),
])
def test_fmb_blank_shares_sum_to_exactly_100(blanks, expected):
    """Regression: 3 blanks each added 0.33, totalling 0.99 - and on the wrong scale: the
    package's SCORE runs 0-100 (decvar maxvalue=100), but each blank added a fraction of
    the item's points."""
    names = [chr(ord("a") + i) for i in range(blanks)]
    stem = "Fill " + " ".join(f"[{n}]" for n in names) + "."
    answers = ", ".join(f"{n}: v{n}" for n in names)
    scores = _fmb_scores(_export(f"{stem}\nAnswers: {answers}"))
    assert [f"{s:.2f}" for s in scores] == expected
    assert sum(scores) == Decimal("100.00")


@pytest.mark.parametrize("blanks", range(1, 16))
def test_fmb_shares_always_total_exactly_100(blanks):
    from app.utils.exporter import _percent_shares
    shares = _percent_shares(blanks)
    assert len(shares) == blanks
    assert sum(shares) == Decimal("100.00")
    assert max(shares) - min(shares) <= Decimal("0.01")


def test_fmb_share_does_not_depend_on_the_questions_points():
    base = "The [a] and [b].\nAnswers: a: x, b: y"
    assert _fmb_scores(_export(base + " (1 point)")) == _fmb_scores(_export(base + " (10 points)"))


def test_fmb_points_possible_is_unchanged():
    root = ET.fromstring(_export("The [a] and [b]. (4 points)\nAnswers: a: x, b: y"))
    entries = {f.findtext("fieldlabel"): f.findtext("fieldentry") for f in root.iter("qtimetadatafield")}
    assert entries["points_possible"] == "4.0"


def test_fmb_synonyms_stay_inside_one_or_condition():
    root = ET.fromstring(_export("Type: FMB\nThe [a] is [b].\na = red\na = crimson\nb = blue"))
    conditions = list(root.iter("respcondition"))
    assert len(conditions) == 2
    assert len(list(conditions[0].iter("or"))) == 1
    assert len(list(conditions[0].iter("varequal"))) == 2
    assert [c.find("setvar").text for c in conditions] == ["50.00", "50.00"]


# --- empty answers -----------------------------------------------------------

def test_empty_core_fmb_answer_is_reported_as_missing():
    q = parse_quiz_text("The [a] and [b].\nAnswers: a: x, b:")[0]
    assert q["type"] == "error"
    assert "b" in q["error"]


def test_empty_respondus_fmb_answer_is_reported_as_missing():
    q = parse_quiz_text("Type: FMB\nThe [a] and [b].\na = x\nb =")[0]
    assert q["type"] == "error"
    assert "b" in q["error"]


def test_exporter_tolerates_empty_answers_in_a_hand_built_question():
    """Defence in depth: an empty synonym used to raise KeyError during export."""
    question = {
        "id": "q0", "type": "fill_in_multiple_blanks_question", "question_text": "The [a] and [b].",
        "variables": {"a": ["x", ""], "b": [""]}, "points": "2",
    }
    xml_text = create_qti_1_2_package("T", [question])
    # only 'a' can be scored, so it carries the whole 100
    assert [f"{s:.2f}" for s in _fmb_scores(xml_text)] == ["100.00"]
