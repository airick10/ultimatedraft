"""
wsgi.py  --  the file that starts Ultimate Draft.

WHAT THIS FILE DOES
    Builds the Flask app (by calling create_app) and exposes it as a variable named `app`.
    There are two ways to start the site, and both end up here:

      flask run         Flask reads FLASK_APP=wsgi.py from the .flaskenv file, imports this file,
                        and looks for the variable `app`.
      python wsgi.py    Python runs this file directly, which triggers the __main__ block at the
                        bottom and starts the Socket.IO server.

    The port is 5050 either way (FLASK_RUN_PORT in .flaskenv for "flask run", port=5050 below
    for "python wsgi.py").

NOTE ON THE IMPORT
    "from ultimatedraft import ..." means the package (the folder holding __init__.py) must be
    named `ultimatedraft`. If you ever rename that folder, change the name here too.

FUNCTIONS
    This file defines none; everything here runs at the top level.
"""

# create_app : the app factory defined in __init__.py
# socketio   : the shared Socket.IO object defined in __init__.py
from ultimatedraft import create_app, socketio

# Build the app once, at import time. "flask run" looks for exactly this name (`app`).
app = create_app()

# This block only runs for "python wsgi.py", NOT for "flask run".
if __name__ == "__main__":
    # socketio.run() is used instead of app.run() so the WebSocket server starts correctly.
    # debug=True turns on auto-reload and the in-browser error pages (development only).
    socketio.run(app, debug=True, port=5050)