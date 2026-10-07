import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from app import app as flask_app, create_app

BASE = "https://localhost"
ROOT = os.path.join(os.path.dirname(__file__), '..')


@pytest.fixture
def client():
    return flask_app.test_client()


def _open(client, method, path):
    return client.open(path, method=method, base_url=BASE)


# --- /api: wrong URL or wrong method is JSON, never the HTML app --------------

@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
@pytest.mark.parametrize("path", ["/api/nope", "/api/nope/deeper", "/api", "/api/"])
def test_unknown_api_url_is_a_json_404(client, method, path):
    """Regression: GET /api/nope was a 200 HTML page, so a client 'succeeded' and then choked
    on HTML where it expected JSON; POST /api/nope was a 405 advertising GET."""
    res = _open(client, method, path)
    assert res.status_code == 404
    assert res.is_json and res.get_json() == {"error": "Not found"}


@pytest.mark.parametrize("method,path,allow", [
    ("GET", "/api/preview", "POST"),        # used to be a 200 HTML page
    ("GET", "/api/download", "POST"),
    ("GET", "/api/canvas", "POST"),
    ("PUT", "/api/download", "POST"),
    ("DELETE", "/api/session", "GET"),
    ("POST", "/api/proxy/progress", "GET"),
])
def test_wrong_method_on_a_real_api_route_is_a_json_405_with_the_real_allow_list(client, method, path, allow):
    res = _open(client, method, path)
    assert res.status_code == 405
    assert res.get_json() == {"error": "Method not allowed"}
    assert res.headers["Allow"] == allow


def test_real_api_routes_still_work(client):
    assert _open(client, "GET", "/api/session").get_json()["canvas"]["connected"] is False
    res = _open(client, "GET", "/api/instructions")
    assert res.status_code == 200 and "attachment" in res.headers["Content-Disposition"]


# --- files that don't exist must not look like the app ------------------------

@pytest.mark.parametrize("path", [
    "/favicon.ico", "/robots.txt", "/sitemap.xml", "/vite.svg", "/missing.js", "/a/b/c.css", "/assets/missing.js",
])
def test_missing_file_like_paths_are_404_not_the_app(client, path):
    res = _open(client, "GET", path)
    assert res.status_code == 404
    assert '<div id="root">' not in res.get_data(as_text=True)


@pytest.mark.parametrize("path", ["/", "/anything", "/a/b/c", "/v1.2/page", "/results/"])
def test_client_side_routes_still_get_the_app_shell(client, path):
    res = _open(client, "GET", path)
    assert res.status_code == 200
    assert '<div id="root">' in res.get_data(as_text=True)


def test_one_static_route_not_two():
    """The hand-written /assets route duplicated Flask's built-in one and was shadowed by it."""
    rules = [r for r in flask_app.url_map.iter_rules() if r.rule == "/assets/<path:filename>"]
    assert [r.endpoint for r in rules] == ["static"]


# --- favicon -----------------------------------------------------------------

def test_the_favicon_the_page_links_is_actually_served(client):
    """Regression: the page linked /vite.svg, but static files are served under /assets/, so the
    request fell into the catch-all and got HTML: no icon."""
    html = _open(client, "GET", "/").get_data(as_text=True)
    assert 'href="/assets/favicon.svg"' in html

    res = _open(client, "GET", "/assets/favicon.svg")
    assert res.status_code == 200
    assert res.mimetype == "image/svg+xml"
    assert b"<svg" in res.data


def test_dev_html_links_the_same_icon_from_public():
    assert 'href="/favicon.svg"' in open(os.path.join(ROOT, "Frontend", "index.html")).read()
    assert os.path.exists(os.path.join(ROOT, "Frontend", "public", "favicon.svg"))


def test_built_bundle_files_are_served_with_sensible_types(client):
    """Guards the manifest -> /assets/<file> mapping that the app shell depends on."""
    manifest = json.load(open(os.path.join(ROOT, "app", "assets", ".vite", "manifest.json")))
    entry = manifest["index.html"]
    js = _open(client, "GET", "/assets/" + entry["file"])
    css = _open(client, "GET", "/assets/" + entry["css"][0])
    assert js.status_code == 200 and "javascript" in js.mimetype
    assert css.status_code == 200 and css.mimetype == "text/css"


# --- security headers --------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/api/session", "/api/nope", "/assets/favicon.svg", "/missing.js"])
def test_baseline_headers_on_every_kind_of_response(client, path):
    res = _open(client, "GET", path)
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["Referrer-Policy"] == "same-origin"


def test_no_frame_restriction_unless_configured(client):
    """Default behaviour is unchanged: guessing wrong would blank the tool inside Canvas."""
    res = _open(client, "GET", "/")
    assert "Content-Security-Policy" not in res.headers


def test_x_frame_options_is_never_sent():
    """It can only say 'never' or 'same origin', which would block Canvas from embedding the tool."""
    for value in (None, "https://school.instructure.com"):
        os.environ.pop("FRAME_ANCESTORS", None)
        if value:
            os.environ["FRAME_ANCESTORS"] = value
        try:
            app = create_app()
        finally:
            os.environ.pop("FRAME_ANCESTORS", None)
        assert "X-Frame-Options" not in app.test_client().get("/", base_url=BASE).headers


def test_frame_ancestors_can_be_restricted_to_the_canvas_hosts(monkeypatch):
    monkeypatch.setenv("FRAME_ANCESTORS", "https://school.instructure.com  https://canvas.school.edu")
    app = create_app()
    client = app.test_client()
    for path in ("/", "/api/session", "/api/nope"):
        assert client.get(path, base_url=BASE).headers["Content-Security-Policy"] == \
            "frame-ancestors 'self' https://school.instructure.com https://canvas.school.edu"


def test_malformed_frame_ancestors_entries_cannot_inject_other_directives(monkeypatch):
    """The value is copied into a response header, so anything but a plain source is dropped."""
    monkeypatch.setenv(
        "FRAME_ANCESTORS",
        "https://ok.example https://evil.example;script-src 'unsafe-inline' \"quoted\" https://also-ok.example",
    )
    with pytest.warns(RuntimeWarning, match="FRAME_ANCESTORS"):
        app = create_app()
    policy = app.test_client().get("/", base_url=BASE).headers["Content-Security-Policy"]
    assert policy == "frame-ancestors 'self' https://ok.example https://also-ok.example"
    assert ";" not in policy and "unsafe" not in policy and '"' not in policy


def test_frame_ancestors_with_only_invalid_entries_adds_no_header(monkeypatch):
    monkeypatch.setenv("FRAME_ANCESTORS", "';evil")
    with pytest.warns(RuntimeWarning):
        app = create_app()
    assert "Content-Security-Policy" not in app.test_client().get("/", base_url=BASE).headers
