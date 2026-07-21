"""Authorization matrix — the highest-value suite in Phase A.

Both confirmed IDORs (SEC-003, SEC-004) were omissions, not logic errors, and
are exactly what this matrix catches. It also asserts the deliberate
404-not-403 disclosure control in docs, which a future authorization
consolidation must not "normalise" into a 403.
"""
from datetime import datetime

import pytest

from app.extensions import db
from app.models import FileAttachment, Meeting, Task
from tests.factories import login, two_org_world


@pytest.fixture
def world(app):
    with app.app_context():
        return two_org_world()


def _register(client, **scope):
    body = {"filename": "x.png", "file_url": "https://example.com/x.png"}
    body.update(scope)
    return client.post("/api/files/register", json=body)


@pytest.mark.integration
@pytest.mark.security
class TestTaskAssignmentIDOR:
    """SEC-003 — tasks.edit_task must reject an out-of-org assignee."""

    def _edit(self, client, task_id, **form):
        base = {"title": "Original title", "priority": "Medium", "status": "Pending"}
        base.update(form)
        return client.post(f"/edit/{task_id}", data=base)

    def test_cross_org_assignment_rejected(self, app, client, world):
        login(client, "admin_a")
        self._edit(client, world["task_a"], assigned_to=str(world["outsider"]))
        with app.app_context():
            assert db.session.get(Task, world["task_a"]).assigned_to != world["outsider"]

    def test_same_org_assignment_accepted(self, app, client, world):
        login(client, "admin_a")
        self._edit(client, world["task_a"], assigned_to=str(world["member_a"]))
        with app.app_context():
            assert db.session.get(Task, world["task_a"]).assigned_to == world["member_a"]

    def test_nonexistent_user_rejected(self, app, client, world):
        login(client, "admin_a")
        self._edit(client, world["task_a"], assigned_to="999999")
        with app.app_context():
            assert db.session.get(Task, world["task_a"]).assigned_to != 999999

    def test_rejected_edit_does_not_persist_other_fields(self, app, client, world):
        # A rejected assignment must not leave the task half-updated in the
        # session for the after-request activity logger to commit. The factory
        # titles this task "A project task"; a rejected edit must preserve it.
        login(client, "admin_a")
        self._edit(client, world["task_a"], title="HIJACK",
                   assigned_to=str(world["outsider"]))
        with app.app_context():
            assert db.session.get(Task, world["task_a"]).title == "A project task"


@pytest.mark.integration
@pytest.mark.security
class TestFileAttachmentIDOR:
    """SEC-004 — files.register_file must authorize every scope."""

    def _count(self, app):
        with app.app_context():
            return FileAttachment.query.count()

    def test_outsider_cannot_attach_to_task(self, app, make_client, world):
        c = login(make_client(), "outsider")
        before = self._count(app)
        r = _register(c, task_id=world["task_a"])
        assert r.status_code == 403
        assert self._count(app) == before

    def test_outsider_cannot_attach_to_discussion(self, app, make_client, world):
        c = login(make_client(), "outsider")
        before = self._count(app)
        r = _register(c, discussion_id=world["discussion_a"])
        assert r.status_code == 403
        assert self._count(app) == before

    def test_nonmember_cannot_attach_to_task(self, app, make_client, world):
        c = login(make_client(), "nobody")
        before = self._count(app)
        r = _register(c, task_id=world["task_a"])
        assert r.status_code == 403
        assert self._count(app) == before

    def test_null_project_does_not_bypass_task_check(self, app, make_client, world):
        c = login(make_client(), "outsider")
        before = self._count(app)
        r = _register(c, project_id=None, task_id=world["task_a"])
        assert r.status_code == 403
        assert self._count(app) == before

    def test_owner_can_attach_to_own_task(self, app, make_client, world):
        c = login(make_client(), "admin_a")
        before = self._count(app)
        r = _register(c, task_id=world["task_a"])
        assert r.status_code == 200
        assert self._count(app) == before + 1


@pytest.mark.integration
class TestProjectAccess:
    """Cross-tenant isolation on project-scoped routes."""

    def test_outsider_cannot_view_project(self, app, make_client, world):
        c = login(make_client(), "outsider")
        r = c.get(f"/projects/{world['project_a']}", follow_redirects=False)
        assert r.status_code in (302, 403, 404)  # denied, not 200

    def test_member_can_view_project(self, app, make_client, world):
        c = login(make_client(), "member_a")
        r = c.get(f"/projects/{world['project_a']}")
        assert r.status_code == 200


@pytest.mark.integration
class TestDocsDisclosureControl:
    """docs deliberately returns 404 (not 403) to non-members so the existence
    of a workspace is not revealed. A future authz consolidation must preserve
    this — assert it explicitly."""

    def test_nonmember_gets_404_not_403(self, app, make_client, world):
        c = login(make_client(), "outsider")
        r = c.get("/orgs/org-a/docs", follow_redirects=False)
        assert r.status_code == 404, (
            "docs must return 404 to non-members, not 403 — this is a "
            "deliberate existence-disclosure control (docs.py:6-7)"
        )


@pytest.mark.integration
class TestMeetingRoomAccess:
    """meetings.meeting_room gates on org membership. B6 migrated this from an
    inline OrgMember query to is_org_member; the access decision must not move."""

    def _make_meeting(self, app, world):
        with app.app_context():
            m = Meeting(title="Standup", org_id=world["org_a"],
                        scheduled_for=datetime(2030, 1, 1, 10, 0),
                        created_by=world["admin_a"], room_name="HiveFlow_Test")
            db.session.add(m)
            db.session.commit()
            return m.id

    def test_member_can_open_meeting_room(self, app, make_client, world):
        mid = self._make_meeting(app, world)
        c = login(make_client(), "member_a")
        assert c.get(f"/meetings/{mid}/room").status_code == 200

    def test_outsider_denied_meeting_room(self, app, make_client, world):
        mid = self._make_meeting(app, world)
        c = login(make_client(), "outsider")
        r = c.get(f"/meetings/{mid}/room", follow_redirects=False)
        assert r.status_code in (302, 403, 404)


@pytest.mark.integration
class TestProjectMutationGates:
    """create_project + add_task gate on org membership. B8 migrated both from an
    inline OrgMember query to is_org_member; an outsider must still be denied."""

    def test_outsider_cannot_open_create_project(self, app, make_client, world):
        c = login(make_client(), "outsider")
        r = c.get("/projects/org-a/create", follow_redirects=False)
        assert r.status_code in (302, 403, 404)

    def test_outsider_cannot_add_task(self, app, make_client, world):
        c = login(make_client(), "outsider")
        with app.app_context():
            before = Task.query.filter_by(project_id=world["project_a"]).count()
        r = c.post(f"/projects/{world['project_a']}/task/add",
                   data={"title": "sneaky", "priority": "Medium"},
                   follow_redirects=False)
        assert r.status_code in (302, 403, 404)
        with app.app_context():
            assert Task.query.filter_by(project_id=world["project_a"]).count() == before


@pytest.mark.integration
class TestMeetingCountApi:
    """meetings.active_meeting_count is an AJAX endpoint that denies with JSON 403
    (C4 migrated it to require_org_member + json_403)."""

    def test_outsider_gets_json_403(self, app, make_client, world):
        c = login(make_client(), "outsider")
        r = c.get(f"/api/projects/{world['project_a']}/meeting/active-count")
        assert r.status_code == 403 and r.get_json()["error"] == "access denied"

    def test_member_gets_200(self, app, make_client, world):
        c = login(make_client(), "member_a")
        assert c.get(f"/api/projects/{world['project_a']}/meeting/active-count").status_code == 200


@pytest.mark.integration
class TestAnalyticsAdminGate:
    """org + project analytics require Admin. B7/B8 migrated the gate from an
    inline `not membership or membership.role != 'Admin'` check to
    `not is_org_admin(...)`; a plain member must still be denied, and an Admin
    still allowed."""

    def test_member_denied_org_analytics(self, app, make_client, world):
        c = login(make_client(), "member_a")  # Member, not Admin, of org_a
        r = c.get("/orgs/org-a/analytics", follow_redirects=False)
        assert r.status_code in (302, 403, 404)

    def test_member_denied_project_analytics(self, app, make_client, world):
        c = login(make_client(), "member_a")
        r = c.get(f"/projects/{world['project_a']}/analytics", follow_redirects=False)
        assert r.status_code in (302, 403, 404)

    def test_admin_allowed_project_analytics(self, app, make_client, world):
        c = login(make_client(), "admin_a")
        assert c.get(f"/projects/{world['project_a']}/analytics").status_code == 200

    def test_member_denied_org_export(self, app, make_client, world):
        c = login(make_client(), "member_a")
        r = c.get("/orgs/org-a/analytics/export.csv", follow_redirects=False)
        assert r.status_code in (302, 403, 404)

    def test_admin_allowed_org_export_csv(self, app, make_client, world):
        c = login(make_client(), "admin_a")
        r = c.get("/orgs/org-a/analytics/export.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("Content-Type", "")


@pytest.mark.integration
class TestSessionIsolation:
    """Guards the harness itself: two clients must not share identity."""

    def test_two_clients_have_distinct_identities(self, app, make_client, world):
        a = login(make_client(), "admin_a")
        o = login(make_client(), "outsider")
        assert "admin_a" in a.get("/auth/profile").get_data(as_text=True)
        assert "outsider" in o.get("/auth/profile").get_data(as_text=True)
