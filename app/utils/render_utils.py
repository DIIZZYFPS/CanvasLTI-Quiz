from flask import render_template
from .vite_manifest import get_vite_assets

def clean_course_id(cid):
    if not cid:
        return ''
    cid_str = str(cid).strip().lower()
    if cid_str in ('none', 'null', 'false', 'undefined', ''):
        return ''
    return str(cid).strip()

def render_app():
    """Render the React app shell.

    Nothing request-specific is injected into the page. The UI used to receive the Canvas
    course id as an inline `window.CANVAS_COURSE_ID` script (an XSS sink that needed careful
    escaping, and a second source of truth that outlived the server session). It now asks
    GET /api/session for the Canvas state instead.
    """
    vite_js_asset, vite_css_asset = get_vite_assets()
    return render_template('index.html', vite_js_asset=vite_js_asset, vite_css_asset=vite_css_asset)
