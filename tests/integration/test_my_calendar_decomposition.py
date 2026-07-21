"""Characterization + behaviour-preservation coverage for my_calendar (CQ-02).

my_calendar had no tests. Before extracting its data-assembly loops into helpers
(_serialize_meetings / _serialize_tasks / _upcoming_meetings / _teams_payload),
this pins the observable output: the page renders and the month's meetings and
in-range tasks appear in the embedded JSON, with their key fields intact.
"""
from datetime import date, datetime

import pytest

from app.extensions import db
from app.models import Meeting, MeetingAttendee, Task
from tests.factories import login, two_org_world


@pytest.fixture
def world(app):
    with app.app_context():
        return two_org_world()


def _seed_month(app, world):
    """A meeting (with the organizer as an attendee) and a personal task, both
    inside the Jan-2030 grid."""
    with app.app_context():
        m = Meeting(title="RenderMtg", org_id=world["org_a"],
                    scheduled_for=datetime(2030, 1, 15, 10, 0),
                    duration_minutes=45, created_by=world["admin_a"],
                    room_name="R1")
        db.session.add(m)
        db.session.flush()
        db.session.add(MeetingAttendee(meeting_id=m.id, user_id=world["admin_a"],
                                       status="Accepted"))
        db.session.add(Task(title="RenderTask", user_id=world["admin_a"],
                            deadline=date(2030, 1, 16), priority="High",
                            status="Pending"))
        db.session.commit()


@pytest.mark.integration
class TestMyCalendarRender:
    def test_renders_month_meetings_and_tasks(self, app, client, world):
        _seed_month(app, world)
        login(client, "admin_a")
        r = client.get("/calendar?month=2030-01")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        # meeting + task serialized into the embedded JSON
        assert "RenderMtg" in body
        assert "RenderTask" in body
        # a field from each serializer path
        assert "Org A" in body          # meeting team name
        assert "High" in body           # task priority

    def test_out_of_range_task_excluded(self, app, client, world):
        _seed_month(app, world)
        login(client, "admin_a")
        # Tasks come only from the viewed month's grid (there is no
        # upcoming-tasks panel), so January's task must not show in June.
        # (The meeting DOES still appear via the month-independent "upcoming"
        # side panel, so it is intentionally not asserted here.)
        r = client.get("/calendar?month=2030-06")
        assert r.status_code == 200
        assert "RenderTask" not in r.get_data(as_text=True)
