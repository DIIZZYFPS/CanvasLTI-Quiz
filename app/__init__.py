import os
import re
import secrets
import warnings
from datetime import timedelta
from flask import Flask, abort, jsonify, request
from flask_caching import Cache
from dotenv import load_dotenv

load_dotenv()

# Placeholder values that have appeared in this repo or its docs. Anyone can read
# them, so a deployment that copied one must not be allowed to sign sessions with it.
_KNOWN_PLACEHOLDER_SECRET_KEYS = {"replace-me-in-production", "your_secure_random_flask_secret"}

# Largest request body accepted (quiz uploads and pasted text). /preview and
# /download are unauthenticated and parse the body in memory, so this bounds the
# work a single request can cause. Override with MAX_UPLOAD_MB.
try:
    MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "10")))
except ValueError:
    MAX_UPLOAD_MB = 10

# Characters allowed in a CSP source (host, scheme, port, wildcard). Anything else in
# FRAME_ANCESTORS is dropped rather than copied into a response header.
_CSP_SOURCE_RE = re.compile(r"[A-Za-z0-9:/.*_\-]+")


def _frame_ancestors_policy():
    """The Content-Security-Policy value restricting who may embed the app in an iframe, or None.

    Canvas embeds this tool in an iframe, so X-Frame-Options (which can only say "never" or
    "same origin") is unusable; `frame-ancestors` can name the Canvas host(s) instead. It is
    opt-in (FRAME_ANCESTORS="https://school.instructure.com https://canvas.school.edu")
    because the right hosts depend on the deployment - a Canvas vanity domain differs from
    CANVAS_DOMAIN - and guessing wrong would blank the tool inside Canvas.
    """
    configured = (os.getenv("FRAME_ANCESTORS") or "").split()
    sources = [token for token in configured if _CSP_SOURCE_RE.fullmatch(token)]
    if len(sources) != len(configured):
        warnings.warn("Ignoring invalid entries in FRAME_ANCESTORS", RuntimeWarning)
    if not sources:
        return None
    return "frame-ancestors 'self' " + " ".join(sources)


# Initialize cache globally so it can be used by other modules via 'from app import cache'
cache = Cache()

def create_app():
    # Use relative paths for static and template folders as they are inside the 'app' package
    app = Flask(__name__, static_folder="assets", template_folder="templates")
    
    CACHE_DIR = os.getenv('CACHE_DIR', '/tmp/flask_cache')
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)

    secret_key = os.getenv("SECRET_KEY")
    if not secret_key or secret_key in _KNOWN_PLACEHOLDER_SECRET_KEYS:
        # Never sign sessions with a publicly known key: that lets anyone forge a
        # session. A random per-process key is safe, but sessions then won't
        # survive a restart or be shared between workers/instances, so LTI launches
        # and Canvas authorization will fail intermittently until SECRET_KEY is set.
        secret_key = secrets.token_hex(32)
        warnings.warn(
            "SECRET_KEY is not set (or is a placeholder). Using a random key "
            "generated at startup: sessions will not survive restarts or be shared "
            "between workers, so LTI launches and Canvas authorization will fail "
            "intermittently. Set the SECRET_KEY environment variable before deploying.",
            RuntimeWarning,
        )

    app.config.from_mapping({
        "DEBUG": False,
        "ENV": "production",
        "CACHE_TYPE": "FileSystemCache",
        "CACHE_DIR": CACHE_DIR,
        "CACHE_DEFAULT_TIMEOUT": 600,
        "SECRET_KEY": secret_key,
        "SESSION_COOKIE_NAME": "pylti1p3-flask-app-sessionid",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": True,
        "SESSION_COOKIE_SAMESITE": 'None',
        "DEBUG_TB_INTERCEPT_REDIRECTS": False,
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=1),
        "MAX_CONTENT_LENGTH": MAX_UPLOAD_MB * 1024 * 1024,
    })

    cache.init_app(app)

    # Register blueprints (Delayed import to avoid circular dependencies)
    from .routes.api import api_bp
    from .routes.lti import lti_bp
    from .routes.auth import auth_bp

    # Register blueprints. API routes are prefixed.
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(lti_bp)
    app.register_blueprint(auth_bp)

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify({"error": f"That upload is too large. The maximum size is {MAX_UPLOAD_MB} MB."}), 413

    frame_ancestors = _frame_ancestors_policy()

    @app.after_request
    def add_security_headers(response):
        # Stop browsers second-guessing declared content types (e.g. running an upload as script).
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # The OAuth callback URL carries a one-time code; never hand it to another site as a Referer.
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if frame_ancestors:
            response.headers.setdefault("Content-Security-Policy", frame_ancestors)
        return response

    def _is_api_path(path):
        return path == "/api" or path.startswith("/api/")

    def _api_wrong_url_or_method():
        """JSON answer for an /api request that didn't reach a handler.

        The SPA catch-all below accepts any GET, so Werkzeug sees *it* as the match for unknown
        API URLs and for wrong-method calls: without this, GET /api/nope was a 200 HTML page,
        GET /api/preview (POST-only) was a 200 HTML page, and POST /api/nope a 405 advertising GET.
        Only real API rules count, so: some rule for this path -> 405 listing its methods,
        otherwise 404.
        """
        allowed = set()
        for rule in app.url_map.iter_rules():
            if rule.endpoint != "serve_react_app" and rule.rule.rstrip("/") == request.path.rstrip("/"):
                allowed |= rule.methods - {"HEAD", "OPTIONS"}
        if allowed:
            response = jsonify({"error": "Method not allowed"})
            response.status_code = 405
            response.headers["Allow"] = ", ".join(sorted(allowed))
            return response
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(404)
    def not_found(error):
        if _is_api_path(request.path):
            return _api_wrong_url_or_method()
        return "Not found", 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        if _is_api_path(request.path):
            return _api_wrong_url_or_method()
        return error

    # Root route for React App. (Static files are served by Flask's own /assets/ route; the
    # hand-written duplicate that used to live here was shadowed by it and never ran.)
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_react_app(path):
        """
        Serves the React application. Any GET that doesn't match an LTI or API route gets
        the app shell, so client-side routes work on reload - except two things that must
        not look like the app:
          * /api/... : a wrong URL or wrong method used to return the HTML page with a 200,
            so a client "succeeded" and then choked on HTML where it expected JSON.
          * anything that looks like a file (/favicon.ico, /robots.txt, /missing.js):
            answering 200 text/html for those breaks favicons, crawlers and asset errors.
        """
        if _is_api_path(request.path):
            return _api_wrong_url_or_method()
        if "." in path.rsplit("/", 1)[-1]:
            abort(404)
        from .utils.render_utils import render_app
        return render_app()

    return app

app = create_app()
