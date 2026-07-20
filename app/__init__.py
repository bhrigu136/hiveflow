from dotenv import load_dotenv
load_dotenv()

import os
from flask import Flask, render_template
from datetime import datetime, timedelta

from app.extensions import db, login_manager, csrf, migrate, limiter
from app.logging_config import configure_logging




def create_app():
    # ── Sentry Error Monitoring (optional, free tier) ────────────────
    sentry_dsn = os.environ.get('SENTRY_DSN')
    if sentry_dsn:
        import sentry_sdk
        sentry_sdk.init(
            dsn=sentry_dsn,
            traces_sample_rate=0.1,  # 10% of requests for performance monitoring
            profiles_sample_rate=0.1,
            environment=os.environ.get('FLASK_ENV', 'production'),
        )

    app = Flask(__name__)

    # ── Secret Key ────────────────────────────────────────────────
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        # Allow insecure fallback ONLY in local dev — crash in production
        if os.environ.get('FLASK_ENV') == 'production':
            raise RuntimeError('SECRET_KEY environment variable must be set in production!')
        secret_key = 'dev-secret-key-change-me'
    app.config['SECRET_KEY'] = secret_key

    # ── Logging ────────────────────────────────────────────────────
    # Configured early so anything below can log. LOG_LEVEL defaults to INFO.
    app.config['LOG_LEVEL'] = os.environ.get('LOG_LEVEL', 'INFO')
    configure_logging(app)

    # ── Upload Safety ──────────────────────────────────────────────
    # Reject any request body larger than 5 MB (profile pictures, forms, etc.)
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

    # ── Session Cookie Hardening ───────────────────────────────────
    app.config['SESSION_COOKIE_SECURE'] = True      # HTTPS-only; browsers ignore on HTTP
    app.config['SESSION_COOKIE_HTTPONLY'] = True     # JS cannot read the cookie
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # Mitigates most CSRF via top-level nav
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
    app.config['REMEMBER_COOKIE_SECURE'] = True
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True

    # ── Database ──────────────────────────────────────────────────
    # Uses PostgreSQL in production (via DATABASE_URL), SQLite locally
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///todo.db')

    # Render provide postgres:// but SQLAlchemy 1.4+ needs postgresql://
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
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    csrf.init_app(app)
    limiter.init_app(app)

    # Jinja global
    app.jinja_env.globals['current_year'] = datetime.now().year
    app.jinja_env.globals['pusher_key'] = os.environ.get('PUSHER_KEY', '')
    app.jinja_env.globals['pusher_cluster'] = os.environ.get('PUSHER_CLUSTER', 'ap2')

    # ── HTTP Security Headers ──────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        if not app.debug:
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains'
            )
        return response

    # ── Login-Session Tracking (Security / Your Devices) ───────────
    @app.before_request
    def _track_login_session():
        from flask import request as req, redirect, url_for, flash
        # Static assets don't need session tracking
        if req.endpoint == 'static':
            return None
        from app.security_utils import track_request
        try:
            still_logged_in = track_request()
        except Exception:
            db.session.rollback()
            return None
        if not still_logged_in:
            # This device was logged out remotely from another session.
            if req.endpoint not in ('auth.login', 'auth.register'):
                flash('Your session was ended from another device. Please sign in again.', 'warning')
                return redirect(url_for('auth.login'))
        return None

    @app.after_request
    def _log_activity(response):
        from app.security_utils import log_activity
        log_activity(response)
        return response

    # ── Custom Error Pages ─────────────────────────────────────────
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(413)
    def request_entity_too_large(e):
        from flask import flash, redirect, request as req
        flash('Upload too large. Maximum file size is 5 MB.', 'danger')
        return redirect(req.referrer or '/'), 413

    @app.errorhandler(500)
    def internal_error(e):
        app.logger.error(f'Server Error: {e}')
        return render_template('errors/500.html'), 500

    # Register blueprints (AFTER extensions)
    from app.routes.auth import auth_bp
    from app.routes.tasks import tasks_bp
    from app.routes.google import google_bp
    from app.routes.orgs import orgs_bp
    from app.routes.projects import projects_bp
    from app.routes.discussions import discussions_bp
    from app.routes.notifications import notifications_bp
    from app.routes.files import files_bp
    from app.routes.meetings import meetings_bp
    from app.routes.tracker import tracker_bp
    from app.routes.calendar import calendar_bp
    from app.routes.meeting_intel import meeting_intel_bp
    from app.routes.docs import docs_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(google_bp)
    app.register_blueprint(orgs_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(discussions_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(meetings_bp)
    app.register_blueprint(tracker_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(meeting_intel_bp)
    app.register_blueprint(docs_bp)

    # Serve robots.txt from the static folder at the root path
    from flask import send_from_directory
    @app.route('/robots.txt')
    def robots_txt():
        return send_from_directory(app.static_folder, 'robots.txt')

    # Import tracker models so SQLAlchemy registers the tables.
    # NOTE: use `from app import ...` — `import app.tracker_models` would
    # rebind the local name `app` to the package module and break the
    # `app.app_context()` call below.
    from app import tracker_models  # noqa: F401

    # Create tables on first run (migrations handle everything after that)
    with app.app_context():
        migrations_dir = os.path.join(app.root_path, '..', 'migrations')
        if not os.path.exists(migrations_dir):
            db.create_all()  # First-time bootstrap only

    return app
