"""Behaviour-preservation coverage for the Google Calendar credential extraction.

Phase B (B2) replaced three byte-identical credential-building blocks in
``app/routes/tasks.py`` with a single call to
``app.google_calendar.build_calendar_service``. These tests pin the behaviour
that must not change:

  1. The helper constructs a ``Credentials`` object from EXACTLY the same fields
     the inline blocks used (token, refresh_token, token_uri, client_id,
     client_secret) and returns a Calendar service — identical to the old code.
  2. Each of the three task routes (add / edit / delete) still reaches the
     calendar API through that shared helper when the user is connected.

The routes are driven with the helper mocked, so no real Google call is made;
the assertion is that the wiring — guard passes -> helper called -> service
used -> event id persisted — is unchanged.
"""
from unittest.mock import MagicMock

import pytest

import app.google_calendar as gcal
from app.extensions import db
from app.models import Task, User
from tests.factories import login


# ── 1. The extracted helper builds identical credentials ──────────────────────

@pytest.mark.integration
class TestBuildCalendarService:
    def test_none_when_not_connected(self):
        """No tokens -> no service, exactly as the inline guards assumed."""
        class Disconnected:
            google_access_token = None
            google_refresh_token = None

        assert gcal.build_calendar_service(Disconnected()) is None

    def test_builds_expected_credentials(self, monkeypatch):
        """A connected user yields Credentials with the same fields the three
        inline blocks used, and a ``build('calendar', 'v3', ...)`` service."""
        captured = {}

        def fake_credentials(**kwargs):
            captured["creds_kwargs"] = kwargs
            return "CREDS_SENTINEL"

        def fake_build(*args, **kwargs):
            captured["build_args"] = args
            captured["build_kwargs"] = kwargs
            return "SERVICE_SENTINEL"

        monkeypatch.setattr(gcal, "Credentials", fake_credentials)
        monkeypatch.setattr(gcal, "build", fake_build)

        class Connected:
            google_access_token = "ATOKEN"
            google_refresh_token = "RTOKEN"

        result = gcal.build_calendar_service(Connected())

        assert result == "SERVICE_SENTINEL"
        # These are precisely the kwargs the removed tasks.py blocks passed.
        assert captured["creds_kwargs"] == {
            "token": "ATOKEN",
            "refresh_token": "RTOKEN",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": gcal.CLIENT_ID,
            "client_secret": gcal.CLIENT_SECRET,
        }
        assert captured["build_args"] == ("calendar", "v3")
        assert captured["build_kwargs"]["credentials"] == "CREDS_SENTINEL"


# ── 2. The three task routes still call the shared helper ─────────────────────

def _make_connected_user(app, username):
    """Create a verified user that looks connected to Google, return their id."""
    with app.app_context():
        u = User(
            username=username,
            email=f"{username}@example.com",
            email_verified=True,
            google_access_token="ATOKEN",
            google_refresh_token="RTOKEN",
        )
        u.set_password("Passw0rd")
        db.session.add(u)
        db.session.commit()
        return u.id


def _fake_service():
    svc = MagicMock()
    svc.events.return_value.insert.return_value.execute.return_value = {"id": "evt_new"}
    return svc


@pytest.mark.integration
class TestTaskRoutesUseSharedHelper:
    def test_add_creates_event_via_helper(self, app, monkeypatch):
        uid = _make_connected_user(app, "gcal_add")
        svc = _fake_service()
        seen = {}

        def fake_builder(user):
            seen["uid"] = user.id
            return svc

        monkeypatch.setattr("app.routes.tasks.build_calendar_service", fake_builder)

        c = login(app.test_client(), "gcal_add")
        r = c.post("/add", data={
            "title": "With deadline", "priority": "High", "deadline": "2030-01-01",
        })

        assert r.status_code in (200, 302)
        assert seen.get("uid") == uid
        svc.events.return_value.insert.assert_called_once()
        with app.app_context():
            t = Task.query.filter_by(title="With deadline").first()
            assert t is not None and t.google_event_id == "evt_new"

    def test_edit_patches_event_via_helper(self, app, monkeypatch):
        uid = _make_connected_user(app, "gcal_edit")
        with app.app_context():
            t = Task(title="Edit me", user_id=uid, google_event_id="evt_existing")
            db.session.add(t)
            db.session.commit()
            tid = t.id

        svc = _fake_service()
        monkeypatch.setattr("app.routes.tasks.build_calendar_service", lambda user: svc)

        c = login(app.test_client(), "gcal_edit")
        r = c.post(f"/edit/{tid}", data={
            "title": "Edited", "priority": "Medium", "deadline": "2030-02-02",
        })

        assert r.status_code in (200, 302)
        svc.events.return_value.patch.assert_called_once()

    def test_delete_removes_event_via_helper(self, app, monkeypatch):
        uid = _make_connected_user(app, "gcal_del")
        with app.app_context():
            t = Task(title="Del me", user_id=uid, google_event_id="evt_del")
            db.session.add(t)
            db.session.commit()
            tid = t.id

        svc = _fake_service()
        monkeypatch.setattr("app.routes.tasks.build_calendar_service", lambda user: svc)

        c = login(app.test_client(), "gcal_del")
        r = c.post(f"/delete/{tid}")

        assert r.status_code in (200, 302)
        svc.events.return_value.delete.assert_called_once()
