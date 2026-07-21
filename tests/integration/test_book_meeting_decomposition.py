"""Behaviour-preservation coverage for the book_meeting decomposition (CQ-02).

book_meeting's attendee-resolution + per-attendee Google-event + invite fan-out
was extracted verbatim into `calendar._invite_meeting_attendees`. These tests
pin that booking still: adds the organizer (auto-accepted) plus real org members
as attendees, filters out non-members, sends invite notifications to invitees
only, and never to the organizer.

Attendees have no Google tokens here, so create_meeting_event returns None (no
real Google call) — exactly the fail-soft path.
"""
import pytest

from app.models import Meeting, MeetingAttendee, Notification
from tests.factories import login, two_org_world


@pytest.fixture
def world(app):
    with app.app_context():
        return two_org_world()


@pytest.mark.integration
class TestBookMeetingInvites:
    def test_booking_creates_attendees_and_invites(self, app, client, world):
        login(client, "admin_a")
        r = client.post("/calendar/book", data={
            "team": "org-a", "title": "Kickoff",
            "date": "2030-01-15", "time": "10:00",
            "attendees": [str(world["member_a"])],
        })
        assert r.status_code in (200, 302)
        with app.app_context():
            meeting = Meeting.query.filter_by(title="Kickoff").first()
            assert meeting is not None and meeting.org_id == world["org_a"]

            rows = MeetingAttendee.query.filter_by(meeting_id=meeting.id).all()
            by_user = {a.user_id: a for a in rows}
            assert set(by_user) == {world["admin_a"], world["member_a"]}
            assert by_user[world["admin_a"]].status == "Accepted"   # organizer
            assert by_user[world["member_a"]].status == "Invited"

            # invitee notified, organizer not
            assert Notification.query.filter_by(user_id=world["member_a"]).count() >= 1
            assert Notification.query.filter_by(user_id=world["admin_a"]).count() == 0

    def test_outsider_passed_as_attendee_is_filtered_out(self, app, client, world):
        login(client, "admin_a")
        r = client.post("/calendar/book", data={
            "team": "org-a", "title": "Private",
            "date": "2030-02-20", "time": "14:00",
            "attendees": [str(world["outsider"])],  # not a member of org_a
        })
        assert r.status_code in (200, 302)
        with app.app_context():
            meeting = Meeting.query.filter_by(title="Private").first()
            attendee_ids = {a.user_id for a in
                            MeetingAttendee.query.filter_by(meeting_id=meeting.id).all()}
            assert attendee_ids == {world["admin_a"]}  # organizer only
            assert Notification.query.filter_by(user_id=world["outsider"]).count() == 0
