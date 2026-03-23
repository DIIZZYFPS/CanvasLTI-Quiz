from flask import render_template
from .vite_manifest import get_vite_assets

def _render_with_globals(template, course_id, api_token):
    """Renders a template and injects CANVAS_COURSE_ID as a window global.
    The API token is intentionally kept server-side only and never sent to the client.
    """
    vite_js_asset, vite_css_asset = get_vite_assets()
    html = render_template(
        template,
        course_id=course_id,
        has_token=bool(api_token),
        vite_js_asset=vite_js_asset,
        vite_css_asset=vite_css_asset,
    )
    if course_id:
        script = f'<script>window.CANVAS_COURSE_ID = "{course_id}";</script>'
        html = html.replace('<head>', f'<head>{script}')
    return html
