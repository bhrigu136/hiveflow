"""Application configuration.

Configuration used to be assembled inline in create_app(), which meant the
factory took no arguments and a test could not ask for an in-memory database or
disable rate limiting without monkey-patching os.environ. Splitting it out is
what makes the application testable.

Environment variable names are unchanged from the inline version. Only the
plumbing moved, so a deployment needs no edits.
"""
import os
from datetime import timedelta


def _normalise_database_url(url: str) -> str:
    """Render and Heroku hand out postgres:// but SQLAlchemy 1.4+ wants
    postgresql://."""
    if url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url


class BaseConfig:
    """Settings shared by every environment.

    Environment variables are read in __init__, not as class attributes, so
    each instantiation sees the current environment. Class-level reads would be
    evaluated once at import time, which silently changes the original
    behaviour: create_app() read os.environ when it was *called*.
    """

    # ── Constants (no environment involved) ──────────────────────────────
    # Reject any request body larger than 5 MB (profile pictures, forms, etc.)
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    # ── Session cookie hardening ─────────────────────────────────────────
    SESSION_COOKIE_SECURE = True      # HTTPS-only; browsers ignore on HTTP
    SESSION_COOKIE_HTTPONLY = True    # JS cannot read the cookie
    SESSION_COOKIE_SAMESITE = 'Lax'   # Mitigates most CSRF via top-level nav
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Feature switches ─────────────────────────────────────────────────
    RATELIMIT_ENABLED = True

    def __init__(self):
        self.SECRET_KEY = os.environ.get('SECRET_KEY')
        self.SQLALCHEMY_DATABASE_URI = _normalise_database_url(
            os.environ.get('DATABASE_URL', 'sqlite:///todo.db')
        )
        self.LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
        self.SENTRY_DSN = os.environ.get('SENTRY_DSN')
        self.PUSHER_KEY = os.environ.get('PUSHER_KEY', '')
        self.PUSHER_CLUSTER = os.environ.get('PUSHER_CLUSTER', 'ap2')

    @property
    def engine_options(self):
        """Connection pooling, for real databases only.

        SQLite ignores pool settings and raises on some of them, so they are
        applied conditionally.
        """
        if self.SQLALCHEMY_DATABASE_URI.startswith('sqlite'):
            return {}
        return {
            'pool_size': 5,
            'pool_recycle': 300,    # recycle connections every 5 min
            'pool_pre_ping': True,  # verify a connection is alive before use
            'max_overflow': 10,
        }

    def validate(self):
        """Raise if a setting required by this environment is missing."""
        return None


class DevConfig(BaseConfig):
    DEBUG = True
    ENV_NAME = 'development'

    def validate(self):
        # A missing SECRET_KEY is tolerated locally, but the fallback must never
        # reach production — see ProdConfig.validate.
        if not self.SECRET_KEY:
            self.SECRET_KEY = 'dev-secret-key-change-me'


class TestConfig(BaseConfig):
    """In-memory database, no rate limiting, CSRF off.

    Everything a test needs to run in isolation without touching the
    environment.
    """
    __test__ = False  # not a pytest test class despite the Test* name
    TESTING = True
    DEBUG = False
    ENV_NAME = 'testing'
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False

    def __init__(self):
        super().__init__()
        self.SECRET_KEY = 'test-secret-key'
        self.SQLALCHEMY_DATABASE_URI = os.environ.get(
            'TEST_DATABASE_URL', 'sqlite:///:memory:'
        )
        self.LOG_LEVEL = 'CRITICAL'   # keep test output readable
        self.SENTRY_DSN = None        # never report from a test run

    @property
    def engine_options(self):
        return {}


class ProdConfig(BaseConfig):
    DEBUG = False
    ENV_NAME = 'production'

    def validate(self):
        if not self.SECRET_KEY:
            raise RuntimeError(
                'SECRET_KEY environment variable must be set in production!'
            )


def get_config(name=None):
    """Resolve a config class from a name, defaulting to FLASK_ENV.

    Defaults to production so that a missing or misspelled FLASK_ENV can never
    quietly enable development behaviour.
    """
    name = (name or os.environ.get('FLASK_ENV') or 'production').strip().lower()
    return {
        'development': DevConfig,
        'testing': TestConfig,
        'test': TestConfig,
        'production': ProdConfig,
    }.get(name, ProdConfig)
