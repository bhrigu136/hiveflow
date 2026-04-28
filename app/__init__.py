from dotenv import load_dotenv
load_dotenv()

import os
from flask import Flask
from datetime import datetime

from app.extensions import db, login_manager, csrf




def create_app():
    app = Flask(__name__)

    # ── Secret Key ────────────────────────────────────────────────
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        # Allow insecure fallback ONLY in local dev — crash in production
        if os.environ.get('FLASK_ENV') == 'production':
            raise RuntimeError('SECRET_KEY environment variable must be set in production!')
        secret_key = 'dev-secret-key-change-me'
    app.config['SECRET_KEY'] = secret_key

    # ── Database ──────────────────────────────────────────────────
    # Uses PostgreSQL in production (via DATABASE_URL), SQLite locally
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///todo.db')

    # Render/Heroku provide postgres:// but SQLAlchemy 1.4+ needs postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Connection pool — important for PostgreSQL under concurrent load
    if not database_url.startswith('sqlite'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 5,
            'pool_recycle': 300,   # recycle connections every 5 min
            'pool_pre_ping': True, # verify connection is alive before using
            'max_overflow': 10,
        }

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    csrf.init_app(app)

    # Jinja global
    app.jinja_env.globals['current_year'] = datetime.now().year

    # Register blueprints (AFTER extensions)
    from app.routes.auth import auth_bp
    from app.routes.tasks import tasks_bp
    from app.routes.google import google_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(google_bp)

    # Create tables
    with app.app_context():
        db.create_all()

    return app
