"""Shared test setup: runs before any test module imports the app.

The app reads its configuration from the environment at import time, so tests must not depend on
whatever happens to be set on the machine (a developer's .env, CI, a production shell). A fixed
SECRET_KEY also keeps the "no SECRET_KEY" warning out of the output (the tests that exercise that
path unset it themselves), and a private cache dir keeps LTI launch state out of /tmp/flask_cache.
"""
import os
import tempfile

os.environ["SECRET_KEY"] = "test-secret-key-" + "x" * 32
os.environ["CACHE_DIR"] = tempfile.mkdtemp(prefix="canvaslti-test-cache-")
for name in ("CANVAS_DOMAIN", "CANVAS_API_CLIENT_ID", "CANVAS_API_CLIENT_SECRET", "CANVAS_OAUTH_REDIRECT_URI",
             "LTI_PRIVATE_KEY", "FRAME_ANCESTORS", "MAX_UPLOAD_MB", "FLASK_DEBUG"):
    os.environ.pop(name, None)
