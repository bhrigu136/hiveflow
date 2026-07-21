from flask import Blueprint, render_template, redirect, url_for, flash, current_app, jsonify, request
from flask_login import login_required, current_user
from app.models import Project, OrgMember, Meeting
from app.authz import check_project_access
import os

meetings_bp = Blueprint('meetings', __name__)

@meetings_bp.route('/projects/<int:project_id>/meeting')
@login_required
def project_meeting(project_id):
    """Renders the collaborative audio/video and screen share meeting room using Jitsi."""
    project = Project.query.get_or_404(project_id)
    if not check_project_access(project):
        flash("You do not have permission to join this meeting room.", 'danger')
        return redirect(url_for('orgs.list_orgs'))

    import hashlib
    # Generate a unique hash using project ID and secret key to keep room private
    salt = current_app.config.get('SECRET_KEY', 'default-salt')
    room_hash = hashlib.md5(f"hiveflow-project-{project.id}-{salt}".encode()).hexdigest()[:12]
    room_name = f"HiveFlow_Meeting_Room_{project.id}_{room_hash}"

    return render_template(
        'projects/meeting.html',
        project=project,
        room_name=room_name,
        current_user=current_user
    )


@meetings_bp.route('/meetings/<int:meeting_id>/room')
@login_required
def meeting_room(meeting_id):
    """Join the Jitsi room for a scheduled team meeting.

    Access is restricted to members of the meeting's organization. The room
    name is stored on the meeting (generated at booking time) so everyone who
    opens this URL lands in the same private room.
    """
    meeting = Meeting.query.get_or_404(meeting_id)

    member = OrgMember.query.filter_by(org_id=meeting.org_id, user_id=current_user.id).first()
    if member is None:
        flash("You do not have permission to join this meeting room.", 'danger')
        return redirect(url_for('calendar.my_calendar'))

    return render_template(
        'calendar/room.html',
        meeting=meeting,
        room_name=meeting.room_name or f"HiveFlow_Meeting_{meeting.id}",
        current_user=current_user,
    )


@meetings_bp.route('/api/projects/<int:project_id>/meeting/active-count')
@login_required
def active_meeting_count(project_id):
    """Returns the mock active user count for this project meeting room.

    In a fully distributed environment, this can query Jitsi's active participants state,
    or read from Redis active states.
    """
    project = Project.query.get_or_404(project_id)
    if not check_project_access(project):
        return jsonify({'error': 'access denied'}), 403

    # For a zero-cost student startup, we can return a randomized or real-time cached count
    # to show that a session is live.
    return jsonify({
        'active_count': 0, # Placeholder (will update dynamically when users join)
        'is_live': False
    })
