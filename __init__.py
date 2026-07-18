from flask import Flask
from flask_socketio import SocketIO

socketio = SocketIO()

def create_app():
    app = Flask(__name__)

    from .routes import main
    app.register_blueprint(main)

    print(app.url_map)

    socketio.init_app(app)

    return app