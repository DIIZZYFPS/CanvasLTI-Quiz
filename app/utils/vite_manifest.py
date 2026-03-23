import json
import os
from flask import current_app


def _load_manifest():
    """Read the Vite manifest.json produced by `vite build --manifest`."""
    manifest_path = os.path.join(current_app.static_folder, '.vite', 'manifest.json')
    if not os.path.exists(manifest_path):
        return None
    with open(manifest_path, 'r') as f:
        return json.load(f)


def get_vite_assets():
    """Return (js_path, css_path) for the main entry point, read from the Vite manifest.
    Falls back to None values if the manifest is unavailable (e.g., dev mode)."""
    manifest = _load_manifest()
    if not manifest:
        return None, None

    # The entry key Vite uses is the relative path from the project root
    entry = manifest.get('index.html') or manifest.get('src/main.tsx') or manifest.get('src/main.ts')
    if not entry:
        # Try to find any entry that looks like the main chunk
        for key, value in manifest.items():
            if value.get('isEntry'):
                entry = value
                break

    if not entry:
        return None, None

    js_file = entry.get('file')
    css_files = entry.get('css', [])
    css_file = css_files[0] if css_files else None

    js_path = f'/assets/{js_file}' if js_file else None
    css_path = f'/assets/{css_file}' if css_file else None
    return js_path, css_path
