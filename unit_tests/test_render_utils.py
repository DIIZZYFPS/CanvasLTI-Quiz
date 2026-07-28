import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask

from app.utils.render_utils import _render_with_globals, clean_course_id

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')


def _make_app():
    return Flask('test_app', template_folder=TEMPLATE_DIR)


def test_clean_course_id_strips_sentinel_values():
    assert clean_course_id(None) == ''
    assert clean_course_id('undefined') == ''
    assert clean_course_id('null') == ''
    assert clean_course_id('  123  ') == '123'


def test_render_with_globals_escapes_quote_breakout():
    """Regression test for a reflected XSS: course_id used to be interpolated
    raw into an inline <script> tag, so a value like `"};alert(1);//` could
    break out of the string literal and execute arbitrary JS."""
    app = _make_app()
    payload = '"};alert(document.cookie);//'
    with app.test_request_context():
        html = _render_with_globals('index.html', payload, None)

    assert 'window.CANVAS_COURSE_ID' in html
    # Raw interpolation (the original bug) would produce this exact breakout
    # sequence right after the opening quote: `""};alert(...)`.
    assert f'"{payload}";' not in html
    # The inner quote must be backslash-escaped so it stays inside the JS
    # string literal instead of terminating it early.
    assert '\\"};alert(document.cookie);//' in html


def test_render_with_globals_escapes_script_tag_breakout():
    """A payload trying to close the <script> tag early and inject a new one
    must not result in a real second <script> element in the output."""
    app = _make_app()
    payload = '</script><script>alert(1)</script>'
    with app.test_request_context():
        html = _render_with_globals('index.html', payload, None)

    assert '</script><script>alert(1)</script>' not in html
    assert 'alert(1)' in html  # value still present, just neutralized


def test_render_with_globals_normal_course_id():
    app = _make_app()
    with app.test_request_context():
        html = _render_with_globals('index.html', '12345', 'some-token')

    assert 'window.CANVAS_COURSE_ID = "12345";' in html


def test_render_with_globals_no_course_id_omits_script():
    app = _make_app()
    with app.test_request_context():
        html = _render_with_globals('index.html', '', None)

    assert 'CANVAS_COURSE_ID' not in html
