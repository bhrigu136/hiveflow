"""Team calendar & meeting scheduling.

A unified calendar where a user sees every meeting across the teams they belong
to (plus their own task deadlines, read-only), and can book a timeslot to
schedule a meeting with selected teammates. Each booking:
  * creates a private Jitsi room (reusing the meetings blueprint room view),
  * notifies every invited attendee in-app,
  * creates a Google Calendar event for each attendee who connected Google.
"""
import calendar as pycal
import hashlib
from datetime import date, datetime, time, timedelta
from sqlalchemy import or_

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app
)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import (
    Organization, OrgMember, Task, Meeting, MeetingAttendee, User
)
from app.utils import create_notification
from app.google_calendar import create_meeting_event, delete_meeting_event
from app.authz import is_org_member

calendar_bp = Blueprint('calendar', __name__)

# Distinct, theme-friendly chip colors assigned per team (by index).
TEAM_COLORS = [
    "#8b5cf6", "#38bdf8", "#22c55e", "#f59e0b",
    "#ec4899", "#14b8a6", "#6366f1", "#ef4444",
]


def _user_orgs():
    """Organizations the current user is a member of, with their membership."""
    memberships = OrgMember.query.filter_by(user_id=current_user.id).all()
    return [(m.organization, m) for m in memberships]


def _color_for(index):
    return TEAM_COLORS[index % len(TEAM_COLORS)]


def _can_manage(meeting, membership_role):
    """Organizer or a team Admin may cancel/manage a meeting."""
    return meeting.created_by == current_user.id or membership_role == 'Admin'


@calendar_bp.route('/calendar')
@login_required
def my_calendar():
    today = date.today()

    # ---- which month are we viewing? ----
    year, month = today.year, today.month
    month_arg = request.args.get('month')
    if month_arg:
        try:
            year, month = (int(x) for x in month_arg.split('-'))
            date(year, month, 1)  # validate
        except (ValueError, TypeError):
            year, month = today.year, today.month

    team_filter = request.args.get('team') or None

    orgs_with_membership = _user_orgs()
    org_index = {org.id: i for i, (org, _) in enumerate(orgs_with_membership)}
    org_ids = list(org_index.keys())
    role_by_org = {org.id: m.role for org, m in orgs_with_membership}

    # ---- month bounds and grid range ----
    first_of_month = date(year, month, 1)
    days_in_month = pycal.monthrange(year, month)[1]
    last_of_month = date(year, month, days_in_month)
    
    cal = pycal.Calendar(firstweekday=6)  # Sunday-first
    weeks_dates = cal.monthdatescalendar(year, month)
    grid_start = weeks_dates[0][0]
    grid_end = weeks_dates[-1][-1]
    
    range_start = datetime.combine(grid_start, time.min)
    range_end = datetime.combine(grid_end, time.max)

    # ---- meetings for this range across the user's teams ----
    meetings = []
    if org_ids:
        q = Meeting.query.filter(
            Meeting.org_id.in_(org_ids),
            Meeting.scheduled_for >= range_start,
            Meeting.scheduled_for <= range_end,
        )
        if team_filter:
            filtered = next((o for o, _ in orgs_with_membership if o.slug == team_filter), None)
            if filtered:
                q = q.filter(Meeting.org_id == filtered.id)
        meetings = q.order_by(Meeting.scheduled_for.asc()).all()

    # ---- tasks (both personal and assigned project tasks) for this range ----
    tasks = Task.query.filter(
        or_(
            Task.user_id == current_user.id,
            Task.assigned_to == current_user.id
        ),
        Task.deadline >= grid_start,
        Task.deadline <= grid_end,
    ).all()

    # ---- serialize meetings to JSON ----
    meetings_json = []
    for mtg in meetings:
        org = mtg.organization
        color = _color_for(org_index.get(mtg.org_id, 0))
        attendees = [
            {
                'name': a.user.name or a.user.username,
                'initial': (a.user.name or a.user.username or 'U')[0].upper(),
                'status': a.status,
            }
            for a in mtg.attendees
        ]
        meetings_json.append({
            'kind': 'meeting',
            'id': mtg.id,
            'title': mtg.title,
            'description': mtg.description or '',
            'scheduled_for': mtg.scheduled_for.isoformat(),
            'end_time_iso': mtg.end_time.isoformat(),
            'time': mtg.scheduled_for.strftime('%I:%M %p').lstrip('0'),
            'end_time': mtg.end_time.strftime('%I:%M %p').lstrip('0'),
            'duration': mtg.duration_minutes,
            'date_label': mtg.scheduled_for.strftime('%A, %b %d'),
            'color': color,
            'team': org.name,
            'team_slug': org.slug,
            'organizer': (mtg.organizer.name or mtg.organizer.username) if mtg.organizer else 'Someone',
            'attendees': attendees,
            'attendee_count': len(attendees),
            'join_url': url_for('meetings.meeting_room', meeting_id=mtg.id),
            'can_manage': _can_manage(mtg, role_by_org.get(mtg.org_id)),
            'cancel_url': url_for('calendar.cancel_meeting', meeting_id=mtg.id),
        })

    # ---- serialize tasks to JSON ----
    tasks_json = []
    for tsk in tasks:
        tasks_json.append({
            'kind': 'task',
            'id': tsk.id,
            'title': tsk.title,
            'description': tsk.description or '',
            'deadline': tsk.deadline.isoformat() if tsk.deadline else None,
            'time_slot': tsk.time_slot.strftime('%H:%M') if tsk.time_slot else None,
            'time': tsk.time_slot.strftime('%I:%M %p').lstrip('0') if tsk.time_slot else None,
            'priority': tsk.priority,
            'status': tsk.status,
            'project_id': tsk.project_id,
            'project_name': tsk.project.name if tsk.project else None,
            'assigned_to': tsk.assigned_to,
            'assignee_name': (tsk.assignee.name or tsk.assignee.username) if tsk.assignee else None,
            'toggle_url': url_for('tasks.toggle_status', task_id=tsk.id),
            'edit_url': url_for('tasks.edit_task', task_id=tsk.id),
            'delete_url': url_for('tasks.delete_task', task_id=tsk.id),
        })

    # ---- upcoming meetings (next 30 days) for the side panel ----
    now = datetime.now()
    upcoming = []
    if org_ids:
        upcoming_rows = Meeting.query.filter(
            Meeting.org_id.in_(org_ids),
            Meeting.scheduled_for >= now,
        ).order_by(Meeting.scheduled_for.asc()).limit(6).all()
        for mtg in upcoming_rows:
            org = mtg.organization
            upcoming.append({
                'id': mtg.id,
                'title': mtg.title,
                'color': _color_for(org_index.get(mtg.org_id, 0)),
                'team': org.name,
                'when': mtg.scheduled_for.strftime('%a, %b %d · %I:%M %p').replace('· 0', '· '),
                'day_num': mtg.scheduled_for.day,
                'month_abbr': mtg.scheduled_for.strftime('%b'),
                'time': mtg.scheduled_for.strftime('%I:%M %p').lstrip('0'),
                'attendee_count': len(mtg.attendees),
                'join_url': url_for('meetings.meeting_room', meeting_id=mtg.id),
            })

    # ---- teams + members payload for the booking modal ----
    teams_data = []
    for org, m in orgs_with_membership:
        members = OrgMember.query.filter_by(org_id=org.id).all()
        teams_data.append({
            'slug': org.slug,
            'name': org.name,
            'members': [
                {'id': mem.user_id,
                 'name': (mem.user.name or mem.user.username),
                 'is_self': mem.user_id == current_user.id}
                for mem in members
            ],
        })

    prev_month = (first_of_month - timedelta(days=1))
    next_month = (last_of_month + timedelta(days=1))

    return render_template(
        'calendar/calendar.html',
        month_name=first_of_month.strftime('%B %Y'),
        year=year,
        month=month,
        prev_month=f"{prev_month.year}-{prev_month.month:02d}",
        next_month=f"{next_month.year}-{next_month.month:02d}",
        this_month=f"{today.year}-{today.month:02d}",
        teams_data=teams_data,
        has_teams=bool(orgs_with_membership),
        upcoming=upcoming,
        team_filter=team_filter,
        today_iso=today.isoformat(),
        default_date=today.isoformat(),
        # Passed as plain Python objects and serialized in the template with
        # `| tojson`, which escapes <, >, & and ' — json.dumps does not, so a
        # value containing </script> could break out of the <script> block.
        meetings_json=meetings_json,
        tasks_json=tasks_json,
    )


def _invite_meeting_attendees(meeting, attendee_ids, join_url, when_label):
    """Create attendee rows for a newly-booked meeting and fan out invites.

    Extracted verbatim from book_meeting. The organizer is always included
    (auto-accepted); only real members of the meeting's org among `attendee_ids`
    are added. Each attendee gets a best-effort Google Calendar event (fails soft
    per user); everyone except the organizer gets an in-app invite notification.
    Does not commit — the caller owns the transaction.
    """
    valid_member_ids = {m.user_id for m in OrgMember.query.filter_by(org_id=meeting.org_id).all()}
    chosen = {int(a) for a in attendee_ids if a.isdigit()} & valid_member_ids
    chosen.add(current_user.id)

    actor_name = current_user.name or current_user.username

    for uid in chosen:
        attendee_user = User.query.get(uid)
        if not attendee_user:
            continue
        attendee = MeetingAttendee(
            meeting_id=meeting.id,
            user_id=uid,
            status='Accepted' if uid == current_user.id else 'Invited',
        )
        # Google Calendar sync (fails soft per-user)
        attendee.google_event_id = create_meeting_event(attendee_user, meeting, join_url=join_url)
        db.session.add(attendee)

        if uid != current_user.id:
            create_notification(
                uid,
                f"{actor_name} invited you to '{meeting.title}' on {when_label}",
                url_for('calendar.my_calendar'),
            )


@calendar_bp.route('/calendar/book', methods=['POST'])
@login_required
def book_meeting():
    org_slug = (request.form.get('team') or '').strip()
    title = (request.form.get('title') or '').strip()
    date_str = (request.form.get('date') or '').strip()
    time_str = (request.form.get('time') or '').strip()
    description = (request.form.get('description') or '').strip()
    duration_raw = (request.form.get('duration') or '30').strip()
    attendee_ids = request.form.getlist('attendees')

    redirect_target = url_for('calendar.my_calendar')

    org = Organization.query.filter_by(slug=org_slug).first()
    if not org:
        flash('Please choose a team for this meeting.', 'danger')
        return redirect(redirect_target)

    if not is_org_member(org.id):
        flash('You are not a member of that team.', 'danger')
        return redirect(redirect_target)

    if not title:
        flash('Give your meeting a title.', 'danger')
        return redirect(redirect_target)

    try:
        scheduled_for = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        flash('Please pick a valid date and time.', 'danger')
        return redirect(redirect_target)

    try:
        duration = max(15, min(480, int(duration_raw)))
    except ValueError:
        duration = 30

    # ---- create the meeting ----
    meeting = Meeting(
        title=title,
        description=description or None,
        org_id=org.id,
        scheduled_for=scheduled_for,
        duration_minutes=duration,
        created_by=current_user.id,
    )
    db.session.add(meeting)
    db.session.flush()  # need the id for the room name

    salt = current_app.config.get('SECRET_KEY', 'default-salt')
    room_hash = hashlib.md5(f"hiveflow-meeting-{meeting.id}-{salt}".encode()).hexdigest()[:12]
    meeting.room_name = f"HiveFlow_Meeting_{meeting.id}_{room_hash}"

    join_url = url_for('meetings.meeting_room', meeting_id=meeting.id, _external=True)
    when_label = scheduled_for.strftime('%b %d at %I:%M %p').replace(' 0', ' ')

    # ---- resolve attendees (organizer always included, members only) + invite ----
    _invite_meeting_attendees(meeting, attendee_ids, join_url, when_label)

    db.session.commit()
    flash(f'Meeting "{title}" scheduled for {when_label}.', 'success')
    return redirect(url_for('calendar.my_calendar',
                            month=f"{scheduled_for.year}-{scheduled_for.month:02d}"))


@calendar_bp.route('/meetings/<int:meeting_id>/cancel', methods=['POST'])
@login_required
def cancel_meeting(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    membership = OrgMember.query.filter_by(org_id=meeting.org_id, user_id=current_user.id).first()
    if not membership:
        flash('You do not have access to that meeting.', 'danger')
        return redirect(url_for('calendar.my_calendar'))

    if not _can_manage(meeting, membership.role):
        flash('Only the organizer or a team admin can cancel this meeting.', 'danger')
        return redirect(url_for('calendar.my_calendar'))

    title = meeting.title
    when_label = meeting.scheduled_for.strftime('%b %d at %I:%M %p').replace(' 0', ' ')
    actor_name = current_user.name or current_user.username
    month_param = f"{meeting.scheduled_for.year}-{meeting.scheduled_for.month:02d}"

    # Remove Google events and notify attendees (except whoever cancelled).
    for attendee in meeting.attendees:
        delete_meeting_event(attendee.user, attendee.google_event_id)
        if attendee.user_id != current_user.id:
            create_notification(
                attendee.user_id,
                f"{actor_name} cancelled '{title}' ({when_label})",
                url_for('calendar.my_calendar'),
            )

    db.session.delete(meeting)
    db.session.commit()
    flash(f'Meeting "{title}" was cancelled.', 'info')
    return redirect(url_for('calendar.my_calendar', month=month_param))


@calendar_bp.route('/meetings/<int:meeting_id>/respond', methods=['POST'])
@login_required
def respond_meeting(meeting_id):
    """Accept or decline an invitation."""
    meeting = Meeting.query.get_or_404(meeting_id)
    response = (request.form.get('response') or '').strip()
    if response not in ('Accepted', 'Declined'):
        flash('Invalid response.', 'danger')
        return redirect(url_for('calendar.my_calendar'))

    attendee = MeetingAttendee.query.filter_by(
        meeting_id=meeting.id, user_id=current_user.id
    ).first()
    if not attendee:
        flash('You are not invited to that meeting.', 'danger')
        return redirect(url_for('calendar.my_calendar'))

    attendee.status = response
    db.session.commit()
    flash(f"You {response.lower()} the invitation to '{meeting.title}'.", 'success')
    return redirect(url_for('calendar.my_calendar',
                            month=f"{meeting.scheduled_for.year}-{meeting.scheduled_for.month:02d}"))
