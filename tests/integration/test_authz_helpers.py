"""Unit coverage for app.authz — the consolidated membership helpers.

These assert the extracted helpers behave exactly as the inline versions did:
a member is a member, a non-member is not, an Admin is an Admin, and a null
org id is never a member.
"""
import pytest

from app.authz import check_project_access, is_org_admin, is_org_member
from tests.factories import login, two_org_world


@pytest.fixture
def world(app):
    with app.app_context():
        return two_org_world()


@pytest.mark.integration
class TestMembershipHelpers:
    def test_member_is_member(self, app, world):
        from app.models import Organization, User
        with app.app_context():
            with app.test_request_context():
                from flask_login import login_user
                user = User.query.get(world["member_a"])
                login_user(user)
                assert is_org_member(world["org_a"]) is True
                assert is_org_member(world["org_b"]) is False

    def test_outsider_is_not_member(self, app, world):
        from app.models import User
        with app.app_context():
            with app.test_request_context():
                from flask_login import login_user
                login_user(User.query.get(world["outsider"]))
                assert is_org_member(world["org_a"]) is False
                assert is_org_member(world["org_b"]) is True

    def test_admin_detection(self, app, world):
        from app.models import User
        with app.app_context():
            with app.test_request_context():
                from flask_login import login_user
                login_user(User.query.get(world["admin_a"]))
                assert is_org_admin(world["org_a"]) is True
                # a plain member is not an admin
                login_user(User.query.get(world["member_a"]))
                assert is_org_admin(world["org_a"]) is False

    def test_null_org_never_member(self, app, world):
        from app.models import User
        with app.app_context():
            with app.test_request_context():
                from flask_login import login_user
                login_user(User.query.get(world["admin_a"]))
                assert is_org_member(None) is False
                assert is_org_admin(None) is False

    def test_check_project_access_matches_membership(self, app, world):
        from app.models import Project, User
        with app.app_context():
            with app.test_request_context():
                from flask_login import login_user
                proj = Project.query.get(world["project_a"])
                login_user(User.query.get(world["member_a"]))
                assert check_project_access(proj) is True
                login_user(User.query.get(world["outsider"]))
                assert check_project_access(proj) is False


@pytest.mark.integration
class TestConsolidatedRoutesUnchanged:
    """The routes that used the duplicated helper must behave identically."""

    def test_member_can_view_discussions(self, app, make_client, world):
        c = login(make_client(), "member_a")
        r = c.get(f"/projects/{world['project_a']}/discussions")
        assert r.status_code == 200

    def test_outsider_denied_discussions(self, app, make_client, world):
        c = login(make_client(), "outsider")
        r = c.get(f"/projects/{world['project_a']}/discussions",
                  follow_redirects=False)
        assert r.status_code in (302, 403, 404)

    def test_member_can_open_meeting_room(self, app, make_client, world):
        c = login(make_client(), "member_a")
        r = c.get(f"/projects/{world['project_a']}/meeting")
        assert r.status_code == 200

    def test_outsider_denied_meeting_room(self, app, make_client, world):
        c = login(make_client(), "outsider")
        r = c.get(f"/projects/{world['project_a']}/meeting",
                  follow_redirects=False)
        assert r.status_code in (302, 403, 404)
