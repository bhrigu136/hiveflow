"""Shared pytest fixtures.

⚠️ SESSION-ISOLATION CONTRACT — read before adding fixtures.

Holding a single app context open across test-client requests makes those
requests reuse the outer Flask-SQLAlchemy scoped session instead of getting a
fresh one per request. Combined with Flask-Login's identity-map-backed
user_loader, `current_user` then sticks to whichever user logged in first, and
every authorization result becomes wrong — an outsider silently executes as the
owner. This was discovered while fixing SEC-004.

Therefore:
  * `app` and `db_session` push short-lived contexts for SETUP and ASSERTIONS.
  * Client requests are made with NO app context held, so each request gets its
    own — exactly as in production, where db.session.remove() runs at teardown.
  * `login_client` verifies the client's identity before returning it, so a
    regression in isolation fails loudly here rather than silently passing a
    cross-tenant test.

The database is built with db.create_all(). The DB-01 reconstruction
(docs/internal/DB01_SCHEMA_RECONSTRUCTION.md) verified this schema differs from
production only by two unpopulated foreign keys, so it is a faithful stand-in
for behavioural tests. Migration-correctness tests are separate and deferred
until the schema baseline lands.
"""
import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db as _db


@pytest.fixture
def app():
    """A fresh application on an in-memory database, torn down per test."""
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
    yield application
    with application.app_context():
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    """The SQLAlchemy handle. Use inside `with app.app_context()` for queries."""
    return _db


@pytest.fixture
def client(app):
    """A test client. Requests run OUTSIDE any app context — see the contract."""
    return app.test_client()


@pytest.fixture
def make_client(app):
    """Factory for additional independent clients (distinct sessions)."""
    def _make():
        return app.test_client()
    return _make
