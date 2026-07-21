from app.extensions import db


def create_notification(user_id, message, link=None):
    from app.models import Notification
    notification = Notification(
        user_id=user_id,
        message=message,
        link=link
    )
    db.session.add(notification)
    # Caller is responsible for db.session.commit()


def notify_org_members(org_id, message, link=None, exclude_user_id=None):
    """Create a notification for every member of an org, optionally skipping one.

    Extracted from the byte-identical "notify all other org members" fan-out
    loops in the discussion routes. Queries the org's members and calls
    ``create_notification`` for each whose ``user_id`` differs from
    ``exclude_user_id`` (typically the actor). Like ``create_notification`` it
    does NOT commit — the caller controls the transaction, preserving the
    previous behaviour where the surrounding view committed once afterward.
    """
    from app.models import OrgMember
    members = OrgMember.query.filter_by(org_id=org_id).all()
    for member in members:
        if member.user_id != exclude_user_id:
            create_notification(member.user_id, message, link)
