import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.utils.text_utils import join_docx_paragraphs
from app.utils.parser import parse_quiz_text


def test_join_inserts_blank_line_between_questions_with_no_blank_paragraphs():
    """Regression test for the real-world bug: a Word document typed as one
    paragraph per line, with paragraph *spacing* (not actual empty
    paragraphs) separating questions. python-docx only sees non-empty
    paragraphs here, so the joiner must infer block boundaries itself."""
    paragraphs = [
        "What is 2+2? (1 point)",
        "A) 3",
        "B) 4",
        "C) 5",
        "Answer: B",
        "SQLite supports full outer join operations natively. (1 point)",
        "Answer: False",
        "What command builds a Vite app for production? (1 point)",
        "Answer: vite build",
    ]
    text = join_docx_paragraphs(paragraphs)
    # Exactly two blank-line separators should have been inserted (3 blocks).
    assert text.count("\n\n") == 2

    questions = parse_quiz_text(text)
    assert len(questions) == 3
    assert [q["type"] for q in questions] == [
        "multiple_choice_question",
        "true_false_question",
        "short_answer_question",
    ]
    assert all(q["type"] != "error" for q in questions)


def test_join_preserves_existing_blank_paragraphs():
    """If a docx *does* already have an empty paragraph between questions,
    the joiner must not collapse or duplicate that separator."""
    paragraphs = [
        "TF: The Earth is round.",
        "Answer: True",
        "",
        "SA: What year did WWII end?",
        "Answer: 1945",
    ]
    text = join_docx_paragraphs(paragraphs)
    questions = parse_quiz_text(text)
    assert len(questions) == 2
    assert questions[0]["type"] == "true_false_question"
    assert questions[1]["type"] == "short_answer_question"


def test_join_handles_respondus_metadata_and_fmb_lines():
    paragraphs = [
        "Type: MC",
        "What is the capital of France?",
        "*A) Paris",
        "B) London",
        "The [color] jumped over the [animal].",
        "Answers: color: red, animal: dog",
    ]
    text = join_docx_paragraphs(paragraphs)
    questions = parse_quiz_text(text)
    assert len(questions) == 2
    assert questions[0]["type"] == "multiple_choice_question"
    assert questions[1]["type"] == "fill_in_multiple_blanks_question"


def test_join_empty_input_returns_empty_string():
    assert join_docx_paragraphs([]) == ""
