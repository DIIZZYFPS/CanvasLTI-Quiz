import os
from datetime import timedelta
from flask import Flask, render_template, send_from_directory
from flask_caching import Cache
from dotenv import load_dotenv

load_dotenv()

# Initialize cache globally so it can be used by other modules via 'from app import cache'
cache = Cache()

def create_app():
    # Use relative paths for static and template folders as they are inside the 'app' package
    app = Flask(__name__, static_folder="assets", template_folder="templates")
    
    SESSION_DIR = os.getenv('SESSION_FILE_DIR', '/tmp/flask_session')
    if not os.path.exists(SESSION_DIR):
        os.makedirs(SESSION_DIR, exist_ok=True)

    app.config.from_mapping({
        "DEBUG": False,
        "ENV": "production",
        "CACHE_TYPE": "SimpleCache",
        "CACHE_DEFAULT_TIMEOUT": 600,
        "SECRET_KEY": os.getenv("SECRET_KEY", "replace-me-in-production"),
        "SESSION_TYPE": "filesystem",
        "SESSION_FILE_DIR": SESSION_DIR,
        "SESSION_COOKIE_NAME": "pylti1p3-flask-app-sessionid",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": True,
        "SESSION_COOKIE_SAMESITE": 'None',
        "DEBUG_TB_INTERCEPT_REDIRECTS": False,
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=1)
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

    # Legacy static assets route
    @app.route('/assets/<path:filename>')
    def assets(filename):
        return send_from_directory(app.static_folder, filename)

    # Root route for React App
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_react_app(path):
        """
        Serves the React application. In production, any request that doesn't match
         an LTI or API route will be served the index.html file, allowing
        React Router to handle the frontend routing.
        """
        return render_template('index.html')

    return app

app = create_app()
