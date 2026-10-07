import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from flask import Flask

from app import app as flask_app
from app.utils.render_utils import clean_course_id, render_app

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')


def test_clean_course_id_strips_sentinel_values():
    assert clean_course_id(None) == ''
    assert clean_course_id('undefined') == ''
    assert clean_course_id('null') == ''
    assert clean_course_id('  123  ') == '123'


def test_render_app_renders_the_shell_without_request_specific_script():
    app = Flask('test_app', template_folder=TEMPLATE_DIR)
    with app.test_request_context('/launch_success?course_id=12345'):
        html = render_app()

    assert '<div id="root">' in html
    # Nothing about the request ends up in the page: the UI asks /api/session instead.
    assert '12345' not in html
    assert 'CANVAS_COURSE_ID' not in html
    assert html.count('<script') == 0 or 'window.' not in html


@pytest.mark.parametrize("payload", [
    '"};alert(document.cookie);//',
    '</script><script>alert(1)</script>',
    '<img src=x onerror=alert(1)>',
])
def test_launch_success_never_reflects_the_course_id_query_param(payload):
    """Regression: course_id used to be interpolated into an inline <script> (a reflected
    XSS that needed careful escaping). The sink is gone: the value is not rendered at all."""
    client = flask_app.test_client()
    res = client.get('/launch_success', query_string={'course_id': payload}, base_url='https://localhost')
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'alert(' not in body
    assert 'CANVAS_COURSE_ID' not in body
    assert '<div id="root">' in body


def test_root_and_unknown_paths_serve_the_same_shell():
    client = flask_app.test_client()
    for path in ('/', '/some/client/route'):
        body = client.get(path, base_url='https://localhost').get_data(as_text=True)
        assert '<div id="root">' in body
