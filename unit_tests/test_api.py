import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from app import app as flask_app
from app.utils.exporter import create_qti_1_2_package
from app.utils.parser import parse_quiz_text

VALID = "What is 2+2?\nA) 3\nB) 4\nAnswer: B"
# One option only -> the parser reports an error for this block.
BROKEN = "Which of these is broken\nA) one\nAnswer: A"


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _post_json(client, path, **body):
    return client.post(path, json=body, base_url="https://localhost")


# --- /api/download validation ------------------------------------------------

def test_download_valid_quiz_returns_zip_with_all_items(client):
    res = _post_json(client, "/api/download", quiz_title="Q", quiz_text=VALID + "\n\n" + VALID)
    assert res.status_code == 200
    xml = zipfile.ZipFile(io.BytesIO(res.data)).read("quiz.qti.xml").decode()
    assert xml.count("<item ") == 2


def test_download_rejects_quiz_containing_error_question(client):
    """Regression: error questions used to be silently dropped, producing a
    'successful' package with fewer questions than the user previewed."""
    res = _post_json(client, "/api/download", quiz_title="Q", quiz_text=VALID + "\n\n" + BROKEN)
    assert res.status_code == 400
    msg = res.get_json()["error"]
    assert "Question 2" in msg
    assert "1 question has errors" in msg


def test_download_error_message_pluralises_and_truncates(client):
    text = "\n\n".join([BROKEN] * 5)
    res = _post_json(client, "/api/download", quiz_title="Q", quiz_text=text)
    assert res.status_code == 400
    msg = res.get_json()["error"]
    assert "5 questions have errors" in msg
    assert "(and 2 more)" in msg


def test_download_rejects_empty_quiz(client):
    res = _post_json(client, "/api/download", quiz_title="Q", quiz_text="")
    assert res.status_code == 400
    assert "No questions" in res.get_json()["error"]


def test_download_rejects_whitespace_only_upload(client):
    res = client.post(
        "/api/download",
        data={"quiz_title": "Q", "file": (io.BytesIO(b"  \n\n  "), "empty.txt")},
        content_type="multipart/form-data",
        base_url="https://localhost",
    )
    assert res.status_code == 400


# --- /api/canvas validation --------------------------------------------------

def test_canvas_rejects_bad_quiz_before_calling_canvas(client, monkeypatch):
    """A quiz with errors must be refused *before* any Canvas request is made,
    so it can't create a half-empty migration."""
    import requests

    def boom(*a, **k):
        raise AssertionError("Canvas must not be contacted for an invalid quiz")

    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")

    with client.session_transaction(base_url="https://localhost") as sess:
        sess["canvas_api_token"] = "tok"
        sess["canvas_course_id"] = "42"

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID + "\n\n" + BROKEN)
    assert res.status_code == 400
    assert "Question 2" in res.get_json()["error"]


def test_canvas_rejects_empty_quiz(client, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Canvas call")))
    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")

    with client.session_transaction(base_url="https://localhost") as sess:
        sess["canvas_api_token"] = "tok"
        sess["canvas_course_id"] = "42"

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text="")
    assert res.status_code == 400


# --- exporter guard ----------------------------------------------------------

def test_exporter_refuses_error_questions():
    questions = parse_quiz_text(VALID + "\n\n" + BROKEN)
    assert [q["type"] for q in questions][-1] == "error"
    with pytest.raises(ValueError):
        create_qti_1_2_package("Q", questions)
