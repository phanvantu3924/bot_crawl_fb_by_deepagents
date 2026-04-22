import os
from flask import Flask


def create_app():
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )

    os.makedirs("logs", exist_ok=True)
    os.makedirs("config", exist_ok=True)
    os.makedirs("data/raw", exist_ok=True)
    os.makedirs("data/cache", exist_ok=True)
    os.makedirs("data/reports", exist_ok=True)

    with app.app_context():
        from .routes import api
        app.register_blueprint(api)

    return app
