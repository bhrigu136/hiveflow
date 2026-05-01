from app.extensions import db
from app.models import ActivityLog

def log_activity(org_id, user_id, action, project_id=None):
    """
    Helper function to log an activity in the database.
    """
    log = ActivityLog(
        org_id=org_id,
        user_id=user_id,
        action=action,
        project_id=project_id
    )
    db.session.add(log)
    # The caller is responsible for calling db.session.commit()

def create_notification(user_id, message, link=None):
    from app.models import Notification
    notification = Notification(
        user_id=user_id,
        message=message,
        link=link
    )
    db.session.add(notification)
    # Caller is responsible for db.session.commit()
