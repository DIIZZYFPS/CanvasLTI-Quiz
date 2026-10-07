import os

from app import app

if __name__ == '__main__':
    # Opt in with FLASK_DEBUG=1. This used to be a hard-coded debug=True, which turns on
    # Werkzeug's interactive debugger: arbitrary code execution for anyone who can reach
    # the port (and it also overrode the app's own DEBUG=False setting).
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
