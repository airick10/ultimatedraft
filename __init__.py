"""
__init__.py  --  the application package for Ultimate Draft.

WHAT THIS FILE DOES
    Python treats a folder with an __init__.py as a "package", and this file runs the first time
    anything imports that package. Here it does two jobs:

      1. Creates the one shared Socket.IO object (`socketio`) that the live draft runs on.
      2. Defines create_app(), the "application factory" that builds the Flask app.

WHO USES IT
    - wsgi.py        imports create_app and socketio from here.
    - routes.py      imports socketio from here  ("from . import socketio")  so it can use
                     @socketio.on(...) handlers and socketio.emit(...).
"""

from flask import Flask                 # the web framework itself
from flask_socketio import SocketIO     # adds WebSockets (live push updates) to Flask

# ---------------------------------------------------------------------------
# The shared Socket.IO object.
#
# It is created here, at module level, and NOT yet attached to an app. It gets attached later
# inside create_app() with socketio.init_app(app).
#
# WHY IT'S DEFINED BEFORE create_app() AND NOT INSIDE IT:
#   routes.py runs "from . import socketio" the moment it is imported. For that import to work,
#   the name `socketio` has to already exist in this file. That is also why routes.py is imported
#   from inside create_app() below, instead of at the top of this file (importing it at the top
#   would make Python load routes.py before `socketio` exists, and the import would fail).
# ---------------------------------------------------------------------------
socketio = SocketIO()


def create_app():
    """
    PURPOSE:
        Build and return the configured Flask application: create the app, attach all of the
        pages and routes (the "main" blueprint in routes.py), and wire Socket.IO into it.
        A function like this is called an "application factory"; it lets tools create a fresh
        app on demand instead of relying on a global one.

    ARGUMENTS:
        none

    CALLED BY:
        - wsgi.py (module level: app = create_app()). Flask finds that `app` variable through
          the setting FLASK_APP=wsgi.py in the .flaskenv file, which is how both "flask run" and
          "python wsgi.py" start the site.

    RETURNS:
        Flask -- the ready-to-run Flask application object.
    """
    # Make the app object. __name__ tells Flask where this package lives, so it can find the
    # "templates" and "static" folders sitting next to this file.
    app = Flask(__name__)

    # Imported here (not at the top of the file) on purpose; see the note above socketio.
    # Importing routes.py also registers every Socket.IO event handler found in it
    # (make_pick, skip_pick, request_sync, start_draft, pause_draft).
    from .routes import main

    # Attach every URL defined in routes.py (the "main" blueprint) to this app.
    app.register_blueprint(main)

    # Connect the shared Socket.IO object to this app. Must happen after the app exists.
    socketio.init_app(app)

    return app