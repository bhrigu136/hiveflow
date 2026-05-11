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
