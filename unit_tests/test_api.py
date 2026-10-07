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


# --- request size limit ------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/preview", "/api/download"])
def test_oversized_json_body_gets_json_413(client, monkeypatch, path):
    monkeypatch.setitem(flask_app.config, "MAX_CONTENT_LENGTH", 1024)
    res = _post_json(client, path, quiz_title="Q", quiz_text="x" * 5000)
    assert res.status_code == 413
    assert "too large" in res.get_json()["error"]


@pytest.mark.parametrize("path", ["/api/preview", "/api/download"])
def test_oversized_upload_gets_json_413(client, monkeypatch, path):
    monkeypatch.setitem(flask_app.config, "MAX_CONTENT_LENGTH", 1024)
    res = client.post(
        path,
        data={"quiz_title": "Q", "file": (io.BytesIO(b"x" * 5000), "big.txt")},
        content_type="multipart/form-data",
        base_url="https://localhost",
    )
    assert res.status_code == 413
    assert "too large" in res.get_json()["error"]


# --- Canvas request timeouts -------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _login(client):
    with client.session_transaction(base_url="https://localhost") as sess:
        sess["canvas_api_token"] = "tok"
        sess["canvas_course_id"] = "42"


def test_canvas_calls_all_pass_a_timeout(client, monkeypatch):
    """Without timeouts a slow Canvas pins a worker thread indefinitely."""
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/content_migrations"):
            return _FakeResponse(200, {
                "pre_attachment": {"upload_url": "https://upload.example.com/x", "upload_params": {}},
                "progress_url": "https://canvas.example.com/api/v1/progress/1",
            })
        return _FakeResponse(201)

    monkeypatch.setattr(requests, "post", fake_post)
    _login(client)

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 200
    assert len(calls) == 2
    for url, kwargs in calls:
        assert kwargs.get("timeout"), f"no timeout on request to {url}"


def test_canvas_timeout_maps_to_504(client, monkeypatch):
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")

    def timeout(*a, **k):
        raise requests.exceptions.ReadTimeout()

    monkeypatch.setattr(requests, "post", timeout)
    _login(client)

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 504
    assert "too long" in res.get_json()["error"]


def test_progress_proxy_passes_timeout_and_maps_to_504(client, monkeypatch):
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    seen = {}

    def timeout(url, **kwargs):
        seen.update(kwargs)
        raise requests.exceptions.ReadTimeout()

    monkeypatch.setattr(requests, "get", timeout)
    _login(client)

    res = client.get(
        "/api/proxy/progress",
        query_string={"url": "https://canvas.example.com/api/v1/progress/1"},
        base_url="https://localhost",
    )
    assert seen.get("timeout")
    assert res.status_code == 504
