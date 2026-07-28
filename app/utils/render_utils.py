import json
from flask import render_template
from .vite_manifest import get_vite_assets

def clean_course_id(cid):
    if not cid:
        return ''
    cid_str = str(cid).strip().lower()
    if cid_str in ('none', 'null', 'false', 'undefined', ''):
        return ''
    return str(cid).strip()

def _render_with_globals(template, course_id, api_token):
    """Renders a template and injects CANVAS_COURSE_ID as a window global.
    The API token is intentionally kept server-side only and never sent to the client.
    """
    course_id = clean_course_id(course_id)
    vite_js_asset, vite_css_asset = get_vite_assets()
    html = render_template(
        template,
        course_id=course_id,
        has_token=bool(api_token),
        vite_js_asset=vite_js_asset,
        vite_css_asset=vite_css_asset,
    )
    if course_id:
        # json.dumps both quotes and JS/HTML-escapes the value (e.g. `<`, `"`),
        # so it can't break out of the string literal or the <script> tag.
        safe_course_id = json.dumps(course_id).replace('<', '\\u003c').replace('>', '\\u003e')
        script = f'<script>window.CANVAS_COURSE_ID = {safe_course_id};</script>'
        html = html.replace('<head>', f'<head>{script}')
    return html
