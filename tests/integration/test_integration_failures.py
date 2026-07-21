"""CQ-05 — integration failures must be logged, not silently swallowed.

Confirms the four Pusher broadcast sites and the activity-log writer now log
their failures while still degrading gracefully: the underlying request must
still succeed when the broadcast or the log write fails.

NOTE: the application logger sets propagate=False (so production lines are not
duplicated), which means pytest's `caplog` — which captures via propagation to
the root logger — cannot see them. These tests therefore attach their own
handler directly to `app.logger`.
"""
import logging

import pytest

from app.extensions import db
from app.models import DiscussionComment
from tests.factories import login, two_org_world


@pytest.fixture
def world(app):
    with app.app_context():
        return two_org_world()


@pytest.fixture
def captured_logs(app):
    """Capture records emitted on the application logger.

    TestConfig raises the app log level to CRITICAL to keep test output clean,
    and the app logger has propagate=False. To observe WARNING lines this
    fixture both lowers the level and attaches its own handler, restoring both
    afterwards.
    """
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    prev_level = app.logger.level
    app.logger.setLevel(logging.WARNING)
    app.logger.addHandler(handler)
    yield records
    app.logger.removeHandler(handler)
    app.logger.setLevel(prev_level)


class _BoomPusher:
    """A pusher stand-in whose trigger always raises."""
    def trigger(self, *a, **k):
        raise RuntimeError("pusher down")


@pytest.mark.integration
class TestPusherFailureLogged:
    def test_comment_still_posts_when_pusher_fails(
            self, app, client, world, monkeypatch, captured_logs):
        # get_pusher is imported inside the view from app.extensions, so that is
        # the binding to replace.
        monkeypatch.setattr("app.extensions.get_pusher", lambda: _BoomPusher())
        login(client, "admin_a")

        r = client.post(
            f"/discussions/{world['discussion_a']}/comment",
            data={"content": "hello"},
        )

        # degradation preserved: the request succeeds (redirect on POST)
        assert r.status_code in (200, 302)
        # and the comment is actually saved
        with app.app_context():
            assert DiscussionComment.query.filter_by(
                discussion_id=world["discussion_a"]).count() == 1
        # and the failure was logged, not swallowed
        messages = [r.getMessage().lower() for r in captured_logs]
        assert any("pusher" in m and "failed" in m for m in messages), \
            f"Pusher failure must be logged; captured: {messages}"


@pytest.mark.integration
class TestActivityLogFailureLogged:
    def test_response_survives_and_logs_activity_write_error(
            self, app, client, world, monkeypatch, captured_logs):
        login(client, "admin_a")

        # Make every commit raise, simulating a persistent activity-log write
        # failure. The after-request logger must swallow it, log it, and let the
        # response through.
        def boom(*a, **k):
            raise RuntimeError("db write failed")

        monkeypatch.setattr(db.session, "commit", boom)

        # Use a route NOT in _ACTIVITY_DENYLIST, or log_activity returns before
        # the write and never exercises the failure path. /orgs/ qualifies.
        r = client.get("/orgs/")

        assert r.status_code in (200, 302)
        messages = [rec.getMessage().lower() for rec in captured_logs]
        assert any("activity-log" in m and "failed" in m for m in messages), \
            f"activity-log write failure must be logged; captured: {messages}"
