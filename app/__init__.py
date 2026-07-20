from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template
from datetime import datetime

from app.config import get_config
from app.extensions import db, login_manager, csrf, migrate, limiter
from app.logging_config import configure_logging




def create_app(config_object=None):
    """Application factory.

    `config_object` accepts a config class, an instance, or a name such as
    'testing'. Omitted, it resolves from FLASK_ENV and defaults to production.
    """
    cfg = config_object if config_object is not None else get_config()
    if isinstance(cfg, str):
        cfg = get_config(cfg)
    if isinstance(cfg, type):
        cfg = cfg()

    # Fail fast on a misconfigured environment rather than at first request.
    cfg.validate()

    # ── Sentry Error Monitoring (optional, free tier) ────────────────
    if cfg.SENTRY_DSN:
        import sentry_sdk
        sentry_sdk.init(
            dsn=cfg.SENTRY_DSN,
            traces_sample_rate=0.1,  # 10% of requests for performance monitoring
            profiles_sample_rate=0.1,
            environment=cfg.ENV_NAME,
        )

    app = Flask(__name__)
    app.config.from_object(cfg)
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = cfg.engine_options

    # ── Logging ────────────────────────────────────────────────────
    # Configured early so anything below can log.
    configure_logging(app)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    csrf.init_app(app)
    limiter.init_app(app)

    # Jinja global
    app.jinja_env.globals['current_year'] = datetime.now().year
    app.jinja_env.globals['pusher_key'] = app.config['PUSHER_KEY']
    app.jinja_env.globals['pusher_cluster'] = app.config['PUSHER_CLUSTER']

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

    # Import the models so SQLAlchemy registers every table. models was
    # previously loaded only as a side effect of blueprint registration, which
    # left Alembic autogenerate depending on blueprint import order.
    # NOTE: use `from app import ...` — `import app.models` would rebind the
    # local name `app` to the package module.
    from app import models  # noqa: F401
    from app import tracker_models  # noqa: F401

    return app
