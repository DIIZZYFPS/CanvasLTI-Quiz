from flask import render_template

def _render_with_globals(template, course_id, api_token):
    """Renders a template and injects CANVAS_COURSE_ID and CANVAS_API_TOKEN as window globals."""
    html = render_template(template, course_id=course_id, has_token=bool(api_token))
    injections = []
    if course_id:
        injections.append(f'window.CANVAS_COURSE_ID = "{course_id}";')
    if api_token:
        injections.append(f'window.CANVAS_API_TOKEN = "{api_token}";')
    if injections:
        script = f'<script>{" ".join(injections)}</script>'
        html = html.replace('<head>', f'<head>{script}')
    return html
