from flask import Blueprint, jsonify, redirect, request
from flask_login import login_required, current_user
from app.models import Notification
from app.extensions import db

notifications_bp = Blueprint('notifications', __name__, url_prefix='/notifications')

@notifications_bp.route('/read/<int:notification_id>', methods=['POST', 'GET'])
@login_required
def mark_read(notification_id):
    notif = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first()
    if notif:
        notif.is_read = True
        db.session.commit()
        if notif.link:
            return redirect(notif.link)
    
    next_url = request.args.get('next')
    return redirect(next_url or '/')

@notifications_bp.route('/read-all', methods=['POST'])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return redirect(request.referrer or '/')
