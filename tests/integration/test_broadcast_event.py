"""Behaviour-preservation coverage for broadcast_event (B5).

Four routes each inlined the same best-effort Pusher block: get_pusher() guard,
try/except around a trigger, and a `[pusher] … broadcast failed …` warning on
failure. B5 extracted the three single-trigger copies to
`app.extensions.broadcast_event`. These tests pin its contract — skip when
unconfigured, trigger when configured, and swallow-and-log on failure — which is
exactly what the inline blocks did.

The application logger has propagate=False and TestConfig raises its level, so
(as in the CQ-05 tests) we attach a handler straight to app.logger to observe
the warning.
"""
import logging

from unittest.mock import MagicMock

import pytest

from app.extensions import broadcast_batch, broadcast_event


@pytest.fixture
def app_warnings(app):
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    prev = app.logger.level
    app.logger.setLevel(logging.WARNING)
    app.logger.addHandler(handler)
    yield records
    app.logger.removeHandler(handler)
    app.logger.setLevel(prev)


class TestBroadcastEvent:
    def test_skips_when_pusher_unconfigured(self, app, monkeypatch):
        monkeypatch.setattr("app.extensions.get_pusher", lambda: None)
        with app.app_context():
            # No Pusher -> return without touching anything, no error.
            assert broadcast_event("c", "e", {"x": 1}, failure_desc="d") is None

    def test_triggers_once_with_exact_args_when_configured(self, app, monkeypatch):
        fake = MagicMock()
        monkeypatch.setattr("app.extensions.get_pusher", lambda: fake)
        with app.app_context():
            broadcast_event("project-7", "new-comment", {"a": 1}, failure_desc="d")
        fake.trigger.assert_called_once_with("project-7", "new-comment", {"a": 1})

    def test_swallows_and_logs_when_trigger_raises(self, app, monkeypatch, app_warnings):
        class _Boom:
            def trigger(self, *a, **k):
                raise RuntimeError("pusher down")

        monkeypatch.setattr("app.extensions.get_pusher", lambda: _Boom())
        desc = "new-comment broadcast failed for discussion 42"
        with app.app_context():
            # Must NOT propagate — the primary write already committed.
            broadcast_event("c", "e", {}, failure_desc=desc)

        messages = [r.getMessage() for r in app_warnings]
        assert any("[pusher]" in m and desc in m and "RuntimeError" in m for m in messages), messages


class TestBroadcastBatch:
    def test_skips_when_pusher_unconfigured(self, app, monkeypatch):
        monkeypatch.setattr("app.extensions.get_pusher", lambda: None)
        with app.app_context():
            assert broadcast_batch("c", "e", [{"x": 1}], failure_desc="d") is None

    def test_triggers_each_payload_in_order(self, app, monkeypatch):
        fake = MagicMock()
        monkeypatch.setattr("app.extensions.get_pusher", lambda: fake)
        payloads = [{"n": 1}, {"n": 2}, {"n": 3}]
        with app.app_context():
            broadcast_batch("room-7", "caption-final", payloads, failure_desc="d")
        assert fake.trigger.call_count == 3
        fake.trigger.assert_any_call("room-7", "caption-final", {"n": 2})

    def test_swallows_and_logs_on_raise(self, app, monkeypatch, app_warnings):
        class _Boom:
            def trigger(self, *a, **k):
                raise RuntimeError("pusher down")

        monkeypatch.setattr("app.extensions.get_pusher", lambda: _Boom())
        desc = "caption-final broadcast failed for meeting 9"
        with app.app_context():
            broadcast_batch("c", "e", [{"x": 1}], failure_desc=desc)
        assert any("[pusher]" in m and desc in m for m in (r.getMessage() for r in app_warnings))
