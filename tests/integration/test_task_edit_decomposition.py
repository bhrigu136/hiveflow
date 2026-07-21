"""Behaviour-preservation coverage for the edit_task decomposition (CQ-02).

edit_task's notification fan-out was extracted verbatim into
`tasks._notify_task_edit` (the Google Calendar side is covered by
test_calendar_service_extraction). This pins that editing a project task still
notifies the new assignee and never the actor — exactly as the inline block did.
"""
import pytest

from app.models import Notification
from tests.factories import login, two_org_world


@pytest.fixture
def world(app):
    with app.app_context():
        return two_org_world()


@pytest.mark.integration
class TestEditTaskNotifications:
    def test_assigning_on_edit_notifies_assignee_not_actor(self, app, client, world):
        login(client, "admin_a")  # admin_a created task_a; is the actor here
        r = client.post(f"/edit/{world['task_a']}", data={
            "title": "A project task", "priority": "Medium",
            "status": "Working", "assigned_to": str(world["member_a"]),
        })
        assert r.status_code in (200, 302)
        with app.app_context():
            # the newly-assigned member is notified
            assert Notification.query.filter_by(user_id=world["member_a"]).count() >= 1
            # the actor is never notified about their own edit
            assert Notification.query.filter_by(user_id=world["admin_a"]).count() == 0

    def test_personal_task_edit_creates_no_notifications(self, app, client, world):
        # personal_a has no project_id -> _notify_task_edit returns immediately
        login(client, "admin_a")
        r = client.post(f"/edit/{world['personal_a']}", data={
            "title": "A personal task", "priority": "High",
        })
        assert r.status_code in (200, 302)
        with app.app_context():
            assert Notification.query.count() == 0
