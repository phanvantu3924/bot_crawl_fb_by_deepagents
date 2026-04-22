import os
from flask import Flask

def create_app():
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')
    
    # Ensure folders exist
    os.makedirs('logs', exist_ok=True)
    os.makedirs('config', exist_ok=True)

    with app.app_context():
        # Register Blueprints
        from .routes import api
        app.register_blueprint(api)
        
    return app
