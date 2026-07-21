"""Sanity checks on the test harness itself.

If these fail, no other test result can be trusted.
"""
import pytest

from app.config import TestConfig


@pytest.mark.unit
def test_testconfig_is_isolated():
    cfg = TestConfig()
    assert cfg.TESTING is True
    assert cfg.WTF_CSRF_ENABLED is False
    assert cfg.RATELIMIT_ENABLED is False
    assert ':memory:' in cfg.SQLALCHEMY_DATABASE_URI
    assert cfg.SENTRY_DSN is None


@pytest.mark.integration
def test_app_boots_and_serves(client):
    for path in ('/auth/login', '/auth/register', '/robots.txt'):
        assert client.get(path).status_code == 200


@pytest.mark.integration
def test_protected_route_redirects_to_login(client):
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


@pytest.mark.integration
def test_all_tables_created(app):
    from app.extensions import db
    with app.app_context():
        # 23 models; alembic_version is not created by create_all
        assert len(db.metadata.tables) == 23
