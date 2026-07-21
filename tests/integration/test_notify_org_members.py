"""Behaviour-preservation coverage for the notification fan-out helper (B4).

`create_discussion` and `add_discussion_comment` each ran a byte-identical
"notify every other org member" loop. B4 extracted it to
`app.utils.notify_org_members`. These tests pin the recipient set (everyone but
the excluded actor), the no-auto-commit contract, and that a discussion post
still notifies the other member but not the poster.
"""
import pytest

from app.extensions import db
from app.models import Notification
from app.utils import notify_org_members
from tests.factories import add_member, login, make_org, make_project, make_user


class TestNotifyOrgMembers:
    def test_excludes_the_actor(self, app):
        with app.app_context():
            admin = make_user("na_admin")
            m2 = make_user("na_m2")
            m3 = make_user("na_m3")
            org = make_org("Notify Co", admin)
            add_member(org, m2)
            add_member(org, m3)
            db.session.commit()
            admin_id, m2_id, m3_id, org_id = admin.id, m2.id, m3.id, org.id

            notify_org_members(org_id, "hello", "/x", exclude_user_id=admin_id)
            db.session.commit()

            got = {n.user_id for n in Notification.query.all()}
            assert got == {m2_id, m3_id}          # the two non-actors
            assert admin_id not in got            # actor skipped
            # message + link carried through
            sample = Notification.query.filter_by(user_id=m2_id).first()
            assert sample.message == "hello" and sample.link == "/x"

    def test_no_exclude_notifies_everyone(self, app):
        with app.app_context():
            admin = make_user("nb_admin")
            m2 = make_user("nb_m2")
            org = make_org("Notify Co B", admin)
            add_member(org, m2)
            db.session.commit()
            org_id, ids = org.id, {admin.id, m2.id}

            notify_org_members(org_id, "hi", None)
            db.session.commit()

            assert {n.user_id for n in Notification.query.all()} == ids

    def test_does_not_commit_on_its_own(self, app):
        """Mirrors create_notification: the helper only stages rows; the caller
        commits. Rolling back after the call must leave nothing persisted."""
        with app.app_context():
            admin = make_user("nc_admin")
            m2 = make_user("nc_m2")
            org = make_org("Notify Co C", admin)
            add_member(org, m2)
            db.session.commit()
            org_id = org.id

            notify_org_members(org_id, "staged", None, exclude_user_id=admin.id)
            db.session.rollback()

            assert Notification.query.count() == 0


@pytest.mark.integration
class TestDiscussionFanOutUnchanged:
    def test_creating_discussion_notifies_other_member_only(self, app, make_client):
        with app.app_context():
            admin = make_user("fo_admin")
            member = make_user("fo_member")
            org = make_org("FanOut Co", admin)
            add_member(org, member)
            proj = make_project(org, admin, name="FO Project")
            db.session.commit()
            admin_id, member_id, proj_id = admin.id, member.id, proj.id

        c = login(make_client(), "fo_admin")
        r = c.post(f"/projects/{proj_id}/discussions/create",
                   data={"title": "Kickoff", "content": "Let's start"})
        assert r.status_code in (200, 302)

        with app.app_context():
            recipients = {n.user_id for n in Notification.query.all()}
            assert member_id in recipients        # the other member is notified
            assert admin_id not in recipients     # the author is not
