import io
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pymupdf
import pytest
from docx import Document

from app.utils.file_reader import read_file
from app.utils.parser import parse_quiz_text

TESTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'Tests')
QUIZ = "What is 2+2?\nA) 3\nB) 4\nAnswer: B\n\nTF: The Earth is round.\nAnswer: True"


class Upload:
    """Stands in for a werkzeug FileStorage: just what read_file touches."""
    def __init__(self, filename, data, content_type=""):
        self.filename, self._data, self.content_type = filename, data, content_type
        self.reads = 0

    def read(self):
        self.reads += 1
        return self._data


def _pdf(text):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in text.split("\n"):
        page.insert_text((72, y), line)
        y += 14
    return doc.tobytes()


def _docx(paragraphs):
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --- text ---------------------------------------------------------------------

@pytest.mark.parametrize("name", ["quiz.txt", "quiz.md", "QUIZ.TXT", "quiz.text"])
def test_text_files_are_read_as_utf8(name):
    assert read_file(Upload(name, QUIZ.encode())) == QUIZ


def test_utf8_text_with_non_ascii_survives():
    text = "Café – naïve 测验 “quoted”\nAnswer: yes"
    assert read_file(Upload("q.txt", text.encode("utf-8"))) == text


@pytest.mark.parametrize("body,first_type", [
    ("Essay: Explain recursion.\nPoints: 5", "essay_question"),
    ("SA: Capital of France?\nAnswer: Paris", "short_answer_question"),
    ("1. What is 2+2?\nA) 3\nB) 4\nAnswer: B", "multiple_choice_question"),
    ("Type: MC\nCapital?\n*A) Paris\nB) Lyon", "multiple_choice_question"),
])
def test_a_byte_order_mark_does_not_break_the_first_question(body, first_type):
    """Regression: Windows Notepad's "UTF-8" option prepends a BOM. Decoded as plain utf-8 it
    stayed in the text as an invisible character, so an `Essay:` first question became an error,
    and the character leaked into the question text and defeated the leading-number strip."""
    text = read_file(Upload("quiz.txt", b"\xef\xbb\xbf" + body.encode()))
    assert not text.startswith("﻿")
    question = parse_quiz_text(text)[0]
    assert question["type"] == first_type
    assert "﻿" not in (question.get("question_text") or "")


def test_text_with_a_text_content_type_is_accepted_whatever_the_extension():
    assert read_file(Upload("quiz.csv", QUIZ.encode(), "text/csv")) == QUIZ


def test_non_utf8_text_is_a_clear_error_not_a_crash():
    with pytest.raises(ValueError, match="not valid UTF-8"):
        read_file(Upload("quiz.txt", "Café".encode("latin-1")))


# --- unsupported / missing ----------------------------------------------------

@pytest.mark.parametrize("name", ["a.doc", "a.xlsx", "a.pptx", "a.zip", "a.png", "a.JPG"])
def test_known_unsupported_formats_say_what_to_convert_to(name):
    with pytest.raises(ValueError, match=r"Unsupported file format .* convert to"):
        read_file(Upload(name, b"data"))


@pytest.mark.parametrize("name", ["a.exe", "a.json", "noextension"])
def test_other_unsupported_files_list_the_supported_ones(name):
    with pytest.raises(ValueError, match=r"Supported formats: \.pdf, \.docx, \.txt, \.md"):
        read_file(Upload(name, b"data"))


@pytest.mark.parametrize("upload", [None, Upload("", b"x"), Upload(None, b"x")])
def test_no_file_is_rejected(upload):
    with pytest.raises(ValueError, match="No file provided"):
        read_file(upload)


# --- PDF ----------------------------------------------------------------------

def test_pdf_text_is_extracted():
    text = read_file(Upload("quiz.pdf", _pdf("What is 2+2?\nA) 3\nB) 4\nAnswer: B")))
    assert "What is 2+2?" in text and "Answer: B" in text
    assert parse_quiz_text(text)[0]["type"] == "multiple_choice_question"


def test_pdf_is_recognised_by_content_type_even_with_a_wrong_extension():
    assert "Hello PDF" in read_file(Upload("export.bin", _pdf("Hello PDF"), "application/pdf"))


def test_corrupt_pdf_is_a_clear_error():
    with pytest.raises(ValueError, match="Failed to parse PDF"):
        read_file(Upload("quiz.pdf", b"%PDF-1.4 this is not really a pdf"))


def test_the_sample_pdf_parses_cleanly():
    with open(os.path.join(TESTS_DIR, "QTI Test Case.pdf"), "rb") as f:
        questions = parse_quiz_text(read_file(Upload("QTI Test Case.pdf", f.read())))
    assert Counter(q["type"] for q in questions) == {
        "multiple_choice_question": 2, "essay_question": 2, "true_false_question": 2, "short_answer_question": 4,
    }


# --- DOCX ---------------------------------------------------------------------

def test_docx_paragraphs_become_questions_without_blank_paragraphs():
    text = read_file(Upload("quiz.docx", _docx(["What is 2+2?", "A) 3", "B) 4", "Answer: B", "TF: The sky is blue.", "Answer: True"])))
    assert [q["type"] for q in parse_quiz_text(text)] == ["multiple_choice_question", "true_false_question"]


def test_docx_is_recognised_by_content_type():
    ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert "Hello Word" in read_file(Upload("export.bin", _docx(["Hello Word"]), ctype))


def test_corrupt_docx_is_a_clear_error():
    with pytest.raises(ValueError, match="Failed to parse DOCX"):
        read_file(Upload("quiz.docx", b"PK this is not a docx"))


# --- general ------------------------------------------------------------------

@pytest.mark.parametrize("name,data", [("q.txt", QUIZ.encode()), ("q.pdf", _pdf("Hi")), ("q.docx", _docx(["Hi"]))])
def test_the_upload_is_read_exactly_once(name, data):
    upload = Upload(name, data)
    read_file(upload)
    assert upload.reads == 1
