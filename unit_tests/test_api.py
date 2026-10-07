import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from app import app as flask_app
from app.utils.exporter import create_qti_1_2_package
from app.utils.parser import parse_quiz_text
from app.utils.session_tokens import SESSION_KEY, encrypt_canvas_token

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

    _login(client)

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID + "\n\n" + BROKEN)
    assert res.status_code == 400
    assert "Question 2" in res.get_json()["error"]


def test_canvas_rejects_empty_quiz(client, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Canvas call")))
    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")

    _login(client)

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
    """Put an authorised Canvas session on the client (token stored encrypted, as in the app)."""
    with flask_app.app_context():
        blob = encrypt_canvas_token("tok")
    with client.session_transaction(base_url="https://localhost") as sess:
        sess[SESSION_KEY] = blob
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
        query_string={"id": "1"},
        base_url="https://localhost",
    )
    assert seen.get("timeout")
    assert res.status_code == 504


# --- quiz titles and the download header -------------------------------------

TITLES = [
    "Bob's Quiz: Intro / Review",
    "Week 3 – Quiz",          # en dash: not Latin-1
    "Prof’s “Final”",  # curly quotes: not Latin-1
    "Café 测验",       # accented + CJK
]


@pytest.mark.parametrize("title", TITLES)
def test_download_header_is_wire_safe_for_any_title(client, title):
    """Regression: a non-Latin-1 title aborted the response with
    UnicodeEncodeError because the header was built by hand. HTTP headers go
    out as Latin-1, so every value must be encodable as such."""
    res = _post_json(client, "/api/download", quiz_title=title, quiz_text="What year?\nAnswer: 1945")
    assert res.status_code == 200
    for name, value in res.headers:
        value.encode("latin-1")  # raises if the server would choke
    disposition = res.headers["Content-Disposition"]
    assert disposition.startswith("attachment")
    if not title.isascii():
        assert "filename*=UTF-8''" in disposition


@pytest.mark.parametrize("title", TITLES)
def test_download_keeps_quiz_title_intact_inside_package(client, title):
    """Regression: the filename sanitiser was also applied to the quiz title,
    so "Bob's Quiz: Intro / Review" became "Bobs Quiz Intro  Review" in Canvas."""
    import xml.etree.ElementTree as ET
    res = _post_json(client, "/api/download", quiz_title=title, quiz_text="What year?\nAnswer: 1945")
    xml = zipfile.ZipFile(io.BytesIO(res.data)).read("quiz.qti.xml")
    assessment = ET.fromstring(xml).find("assessment")
    assert assessment.get("title") == title


def test_download_filename_is_sanitised(client):
    res = _post_json(client, "/api/download", quiz_title="a/b:c*d?", quiz_text="What year?\nAnswer: 1945")
    assert 'abcd_package.zip' in res.headers["Content-Disposition"]


def test_download_title_control_characters_are_neutralised(client):
    import xml.etree.ElementTree as ET
    res = _post_json(client, "/api/download", quiz_title="Line1\nLine2\x00\x07", quiz_text="What year?\nAnswer: 1945")
    assert res.status_code == 200
    xml = zipfile.ZipFile(io.BytesIO(res.data)).read("quiz.qti.xml")
    assessment = ET.fromstring(xml).find("assessment")
    assert assessment.get("title") == "Line1 Line2"


def test_download_blank_title_falls_back(client):
    res = _post_json(client, "/api/download", quiz_title="   ", quiz_text="What year?\nAnswer: 1945")
    assert res.status_code == 200
    assert "quiz_package.zip" in res.headers["Content-Disposition"]


@pytest.mark.parametrize("path", ["/api/preview", "/api/download"])
@pytest.mark.parametrize("body", [
    {"quiz_title": 123, "quiz_text": "What year?\nAnswer: 1945"},
    {"quiz_title": "Q", "quiz_text": 123},
    {"quiz_title": "Q", "quiz_text": ["a", "b"]},
])
def test_wrongly_typed_json_fields_are_a_400_not_a_500(client, path, body):
    res = client.post(path, json=body, base_url="https://localhost")
    if path == "/api/preview" and isinstance(body["quiz_text"], str):
        assert res.status_code == 200  # preview ignores the title
        return
    assert res.status_code == 400
    assert "attribute" not in res.get_json()["error"]


def test_non_object_json_body_does_not_crash(client):
    res = client.post("/api/download", json=["not", "an", "object"], base_url="https://localhost")
    assert res.status_code == 400


# --- error responses don't leak internals ------------------------------------

def test_unexpected_download_error_is_generic(client, monkeypatch):
    import app.routes.api as api_module

    def explode(*a, **k):
        raise RuntimeError("secret internal detail /srv/app/db.sqlite")

    monkeypatch.setattr(api_module, "create_qti_1_2_package", explode)
    res = _post_json(client, "/api/download", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 500
    assert "secret" not in res.get_data(as_text=True)


class _ErrorResponse(_FakeResponse):
    def raise_for_status(self):
        import requests
        raise requests.exceptions.HTTPError(response=self)


def test_canvas_http_error_shows_message_not_raw_json(client, monkeypatch):
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    raw = '{"errors":[{"message":"The specified resource does not exist."}],"error_report_id":98765}'
    resp = _ErrorResponse(404, {"errors": [{"message": "The specified resource does not exist."}]})
    resp.text = raw
    monkeypatch.setattr(requests, "post", lambda *a, **k: resp)
    _login(client)

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 502
    msg = res.get_json()["error"]
    assert "The specified resource does not exist." in msg
    assert "404" in msg
    assert "{" not in msg and "98765" not in msg


def test_canvas_unexpected_error_is_generic(client, monkeypatch):
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")

    def explode(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(requests, "post", explode)
    _login(client)

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 500
    assert "secret" not in res.get_data(as_text=True)


def test_canvas_attachment_name_uses_filename_safe_title(client, monkeypatch):
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    sent = {}

    def fake_post(url, **kwargs):
        if url.endswith("/content_migrations"):
            sent["payload"] = kwargs["json"]
            return _FakeResponse(200, {
                "pre_attachment": {"upload_url": "https://upload.example.com/x", "upload_params": {}},
                "progress_url": "https://canvas.example.com/api/v1/progress/1",
            })
        sent["upload_name"] = kwargs["files"]["file"][0]
        return _FakeResponse(201)

    monkeypatch.setattr(requests, "post", fake_post)
    _login(client)

    res = _post_json(client, "/api/canvas", quiz_title="Bob's Quiz: Intro / Review", quiz_text=VALID)
    assert res.status_code == 200
    assert sent["payload"]["pre_attachment"]["name"] == "Bobs Quiz Intro Review.zip"
    assert sent["upload_name"] == "Bobs Quiz Intro Review.zip"


# --- course id validation ----------------------------------------------------

@pytest.mark.parametrize("bad", ["42/../../../users/self", "42?x=1", "abc", "4 2", "42#frag", "lti_context_id:abc", [42], {"a": 1}])
def test_non_numeric_course_id_is_rejected_before_any_canvas_call(client, monkeypatch, bad):
    """The course id is interpolated into a Canvas API path, so it must be digits."""
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Canvas call")))
    _login(client)

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID, course_id=bad)
    assert res.status_code == 400
    assert "course ID" in res.get_json()["error"]


def test_non_numeric_course_id_from_the_session_is_rejected(client, monkeypatch):
    """e.g. an LTI launch that fell back to the opaque context claim instead of the numeric id."""
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Canvas call")))
    _login(client)
    with client.session_transaction(base_url="https://localhost") as sess:
        sess["canvas_course_id"] = "6d1c2e5a-aaaa-bbbb-cccc-0123456789ab"

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 400


def test_numeric_course_id_is_used_in_the_migration_url(client, monkeypatch):
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    urls = []

    def fake_post(url, **kwargs):
        urls.append(url)
        if url.endswith("/content_migrations"):
            return _FakeResponse(200, {"pre_attachment": {"upload_url": "https://upload.example.com/x", "upload_params": {}},
                                       "progress_url": "https://canvas.example.com/api/v1/progress/9"})
        return _FakeResponse(201)

    monkeypatch.setattr(requests, "post", fake_post)
    _login(client)
    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID, course_id="12345")
    assert res.status_code == 200
    assert urls[0] == "https://canvas.example.com/api/v1/courses/12345/content_migrations"


# --- finishing the upload ----------------------------------------------------

class _Redirect(_FakeResponse):
    def __init__(self, location=None, status=303):
        super().__init__(status)
        self.headers = {"Location": location} if location else {}


def _setup_redirecting_canvas(monkeypatch, upload_response, finalize_response=None, upload_url="https://upload.example.com/x"):
    """Fake Canvas: migration OK, upload answers `upload_response`, finalize GET answers `finalize_response`."""
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    gets = []

    def fake_post(url, **kwargs):
        if url.endswith("/content_migrations"):
            return _FakeResponse(200, {"pre_attachment": {"upload_url": upload_url, "upload_params": {}},
                                       "progress_url": "https://canvas.example.com/api/v1/progress/77"})
        return upload_response

    def fake_get(url, **kwargs):
        gets.append((url, kwargs))
        return finalize_response or _FakeResponse(201)

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)
    return gets


def test_upload_redirect_is_followed_with_authorization(client, monkeypatch):
    """Regression: Canvas' upload protocol requires GETting the redirect (with
    auth) to confirm the upload. It used to be ignored, so on installs that answer
    with a redirect the file stayed pending and the quiz never imported."""
    target = "https://canvas.example.com/api/v1/files/9/create_success?uuid=abc"
    gets = _setup_redirecting_canvas(monkeypatch, _Redirect(target))
    _login(client)

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 200
    assert len(gets) == 1
    url, kwargs = gets[0]
    assert url == target
    assert kwargs["headers"] == {"Authorization": "Bearer tok"}
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"]


def test_relative_redirect_is_resolved_against_the_upload_url(client, monkeypatch):
    gets = _setup_redirecting_canvas(
        monkeypatch, _Redirect("/api/v1/files/9/create_success"),
        upload_url="https://canvas.example.com/files_api",
    )
    _login(client)
    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 200
    assert gets[0][0] == "https://canvas.example.com/api/v1/files/9/create_success"


@pytest.mark.parametrize("evil", [
    "https://evil.example.net/steal",
    "http://canvas.example.com/api/v1/files/9/create_success",   # scheme downgrade
    "https://canvas.example.com.evil.net/x",
    "//evil.example.net/x",
])
def test_token_is_never_sent_to_a_non_canvas_redirect(client, monkeypatch, evil):
    gets = _setup_redirecting_canvas(monkeypatch, _Redirect(evil))
    _login(client)

    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 502
    assert gets == [], "the bearer token must not be sent anywhere but Canvas"
    assert "unexpected upload redirect" in res.get_json()["error"]


def test_redirect_without_location_is_an_error(client, monkeypatch):
    _setup_redirecting_canvas(monkeypatch, _Redirect(None))
    _login(client)
    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 502


def test_plain_201_upload_needs_no_followup_request(client, monkeypatch):
    gets = _setup_redirecting_canvas(monkeypatch, _FakeResponse(201))
    _login(client)
    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 200
    assert gets == []


def test_finalize_401_clears_the_token_and_asks_to_relaunch(client, monkeypatch):
    _setup_redirecting_canvas(
        monkeypatch, _Redirect("https://canvas.example.com/api/v1/files/9/create_success"),
        finalize_response=_FakeResponse(401),
    )
    _login(client)
    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 401
    assert _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID).get_json()["error"].startswith("Missing Canvas API Token")


def test_finalize_failure_is_reported_not_swallowed(client, monkeypatch):
    bad = _ErrorResponse(500, {"errors": [{"message": "Something broke"}]})
    _setup_redirecting_canvas(
        monkeypatch, _Redirect("https://canvas.example.com/api/v1/files/9/create_success"),
        finalize_response=bad,
    )
    _login(client)
    res = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID)
    assert res.status_code == 502
    assert "Something broke" in res.get_json()["error"]


# --- progress by id ----------------------------------------------------------

def test_canvas_response_includes_the_progress_id(client, monkeypatch):
    _setup_redirecting_canvas(monkeypatch, _FakeResponse(201))
    _login(client)
    body = _post_json(client, "/api/canvas", quiz_title="Q", quiz_text=VALID).get_json()
    assert body["progress_id"] == "77"


def test_progress_proxy_builds_the_canvas_url_itself(client, monkeypatch):
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com/")
    seen = []

    def fake_get(url, **kwargs):
        seen.append((url, kwargs))
        return _FakeResponse(200, {"workflow_state": "running", "completion": 40})

    monkeypatch.setattr(requests, "get", fake_get)
    _login(client)
    res = client.get("/api/proxy/progress", query_string={"id": "123"}, base_url="https://localhost")

    assert res.status_code == 200
    assert res.get_json()["completion"] == 40
    assert seen[0][0] == "https://canvas.example.com/api/v1/progress/123"
    assert seen[0][1]["headers"] == {"Authorization": "Bearer tok"}


@pytest.mark.parametrize("params", [
    {},
    {"id": ""},
    {"id": "abc"},
    {"id": "1/../../users/self"},
    {"id": "1?x=2"},
    {"id": "1 2"},
    {"url": "https://canvas.example.com/api/v1/progress/1"},   # the old, URL-taking form
])
def test_progress_proxy_rejects_anything_but_a_numeric_id(client, monkeypatch, params):
    import requests

    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Canvas call")))
    _login(client)
    res = client.get("/api/proxy/progress", query_string=params, base_url="https://localhost")
    assert res.status_code == 400


def test_progress_proxy_without_a_session_is_401(client, monkeypatch):
    monkeypatch.setenv("CANVAS_DOMAIN", "https://canvas.example.com")
    res = client.get("/api/proxy/progress", query_string={"id": "1"}, base_url="https://localhost")
    assert res.status_code == 401
