# Flask-ToDo_App\app\routes\tasks.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, abort
from flask_login import login_required, current_user
from datetime import datetime, time, timedelta, date, timezone
from sqlalchemy import or_
from app.extensions import db
from app.models import Task, Project, OrgMember
from app.utils import create_notification
from app.google_calendar import build_calendar_service

import csv
import io


tasks_bp = Blueprint('tasks', __name__)


# VIEW TASKS
@tasks_bp.route('/')
@login_required
def view_tasks():
    status_filter = request.args.get('status', 'all')
    priority_filter = request.args.get('priority', 'all')
    search = request.args.get('q', '').strip()
    date_filter_raw = request.args.get('date', '').strip()

    today = date.today()
    show_all = date_filter_raw == 'all'
    selected_date = None

    if not show_all:
        if date_filter_raw:
            try:
                selected_date = datetime.strptime(date_filter_raw, "%Y-%m-%d").date()
            except ValueError:
                selected_date = today
        else:
            # Default view = today only
            selected_date = today

    # Personal view: only personal tasks. Project tasks live on their project board.
    query = Task.query.filter_by(user_id=current_user.id).filter(Task.project_id.is_(None))

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    if priority_filter != 'all':
        query = query.filter_by(priority=priority_filter)

    if search:
        query = query.filter(Task.title.ilike(f'%{search}%'))

    if selected_date is not None:
        if selected_date == today:
            # Today's view also surfaces undated tasks so they don't get lost
            query = query.filter(or_(Task.deadline == selected_date, Task.deadline.is_(None)))
        else:
            query = query.filter(Task.deadline == selected_date)

    tasks = query.order_by(
        Task.deadline.desc(),
        Task.time_slot.desc(),
        Task.created_at.desc()
    ).all()

    # Stats for the dashboard summary — based on the currently visible task set
    total_count = len(tasks)
    pending_count = sum(1 for t in tasks if t.status == 'Pending')
    working_count = sum(1 for t in tasks if t.status == 'Working')
    completed_count = sum(1 for t in tasks if t.status == 'Completed')
    completion_pct = int((completed_count / total_count) * 100) if total_count else 0

    # Build prev/next dates and a friendly label for the day-navigation bar
    prev_date = (selected_date - timedelta(days=1)).isoformat() if selected_date else None
    next_date = (selected_date + timedelta(days=1)).isoformat() if selected_date else None

    if show_all:
        day_label = "All Tasks"
    elif selected_date == today:
        day_label = "Today"
    elif selected_date == today - timedelta(days=1):
        day_label = "Yesterday"
    elif selected_date == today + timedelta(days=1):
        day_label = "Tomorrow"
    else:
        day_label = selected_date.strftime('%A, %b %d, %Y')

    # Persist active filters on the day-nav links
    nav_args = {}
    if status_filter != 'all':
        nav_args['status'] = status_filter
    if priority_filter != 'all':
        nav_args['priority'] = priority_filter
    if search:
        nav_args['q'] = search

    return render_template(
        'tasks.html',
        tasks=tasks,
        status_filter=status_filter,
        priority_filter=priority_filter,
        search=search,
        date_filter=selected_date.isoformat() if selected_date else '',
        selected_date=selected_date,
        show_all=show_all,
        is_today=(selected_date == today),
        prev_date=prev_date,
        next_date=next_date,
        day_label=day_label,
        nav_args=nav_args,
        total_count=total_count,
        pending_count=pending_count,
        working_count=working_count,
        completed_count=completed_count,
        completion_pct=completion_pct,
    )



# ADD TASK

@tasks_bp.route('/add', methods=['POST'])
@login_required
def add_task():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    priority = request.form.get('priority', 'Medium')
    deadline_str = request.form.get('deadline', '').strip()
    time_str = request.form.get('time_slot', '').strip()

    if not title:
        flash('Task title cannot be empty.', 'danger')
        return redirect(url_for('tasks.view_tasks'))
    
    if len(title) > 100:
        flash('Task title must be 100 characters or less.', 'danger')
        return redirect(url_for('tasks.view_tasks'))

    
    # DEADLINE PARSING (DATE)
    
    deadline = None
    if deadline_str:
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        except ValueError:
            flash('Invalid date format for deadline.', 'danger')
            return redirect(url_for('tasks.view_tasks'))

    
    # TIME SLOT PARSING (TIME)
    
    time_slot = None
    if time_str:
        try:
            time_slot = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            flash('Invalid time format.', 'danger')
            return redirect(url_for('tasks.view_tasks'))

    
    # COMBINE DATE + TIME
    
    deadline_datetime = None
    if deadline and time_slot:
        deadline_datetime = datetime.combine(deadline, time_slot)
    elif deadline:
        # Default reminder time if user gives only date
        deadline_datetime = datetime.combine(deadline, time(9, 0))

    # (IMPORTANT)
    # We are NOT storing deadline_datetime yet.
    # This will be used for Google Calendar in next step.

    
    # CREATE TASK
    
    task = Task(
        title=title,
        description=description if description else None,
        priority=priority,
        deadline=deadline,
        time_slot=time_slot,
        user_id=current_user.id
    )

    db.session.add(task)
    db.session.commit()

    # CREATE GOOGLE CALENDAR EVENT (IF CONNECTED)
    _create_task_calendar_event(task, deadline_datetime)

    flash('Task added successfully!', 'success')
    return redirect(url_for('tasks.view_tasks'))


# Authorization helper for tasks that may belong to a project (org-scoped).
# action: 'status' (toggle), 'edit', or 'delete'.
def _authorize_task(task_id, action):
    task = Task.query.get_or_404(task_id)

    def _deny(reason, status=403):
        print(
            f"[TASK AUTH DENY] action={action} task_id={task_id} "
            f"user_id={current_user.id} task.user_id={task.user_id} "
            f"task.project_id={task.project_id} task.assigned_to={task.assigned_to} "
            f"reason={reason} -> {status}"
        )
        abort(status)

    # Personal task (not part of a project) — owner only, same as before.
    if not task.project_id:
        if task.user_id != current_user.id:
            _deny("personal task not owned by user", 404)
        return task

    # Project task — check org membership and role.
    project = Project.query.get(task.project_id)
    if not project:
        _deny("project missing", 404)

    membership = OrgMember.query.filter_by(
        org_id=project.org_id, user_id=current_user.id
    ).first()
    if not membership:
        _deny(f"user not a member of org {project.org_id}")

    is_admin = membership.role == 'Admin'

    if action == 'status':
        # Admin can toggle anything; a regular member can toggle only tasks assigned to them.
        if is_admin or task.assigned_to == current_user.id:
            return task
        _deny("not admin and not assignee")

    # 'edit' and 'delete' — admin only.
    if is_admin:
        return task
    _deny("not admin")


def _notify_task_edit(task, prev_assigned_to, prev_status):
    """Notify the relevant people about a project-task edit.

    Extracted verbatim from edit_task. Only project tasks notify. A status
    change gets a tailored message; anything else is a generic 'edited'. The
    actor is never notified. Does not commit — the caller owns the transaction.
    """
    if not task.project_id:
        return

    actor_name = current_user.name or current_user.username
    link = url_for('projects.dashboard', project_id=task.project_id)
    notified = {current_user.id}

    # 1. If the assignee changed, ping the new assignee specifically
    if task.assigned_to and task.assigned_to != prev_assigned_to and task.assigned_to not in notified:
        create_notification(
            task.assigned_to,
            f"{actor_name} assigned you the task '{task.title}'",
            link,
        )
        notified.add(task.assigned_to)

    # 2. Notify existing audience (creator + current assignee) about the edit
    if task.status != prev_status:
        message_template = f"{actor_name} moved '{task.title}' to {task.status}"
    else:
        message_template = f"{actor_name} edited the task '{task.title}'"

    if task.assigned_to and task.assigned_to not in notified:
        create_notification(task.assigned_to, message_template, link)
        notified.add(task.assigned_to)
    if task.created_by and task.created_by not in notified:
        create_notification(task.created_by, message_template, link)


def _update_task_calendar_event(task, deadline, time_slot):
    """Patch the task's Google Calendar event after an edit, if one exists.

    Extracted verbatim from edit_task. Best-effort: runs only when the task has
    a synced event, the user is connected to Google, and a date/time was given;
    a Google failure is logged and never blocks the edit.
    """
    if not (
        task.google_event_id
        and current_user.google_access_token
        and current_user.google_refresh_token
        and (deadline or time_slot)
    ):
        return

    try:
        # Rebuild datetime
        deadline_datetime = None
        if deadline and time_slot:
            deadline_datetime = datetime.combine(deadline, time_slot)
        elif deadline:
            deadline_datetime = datetime.combine(deadline, time(9, 0))

        if deadline_datetime:
            service = build_calendar_service(current_user)

            updated_event = {
                "summary": f"To-Do: {task.title}",
                "description": f"Priority: {task.priority}",
                "start": {
                    "dateTime": deadline_datetime.isoformat(),
                    "timeZone": "Asia/Kolkata",
                },
                "end": {
                    "dateTime": (deadline_datetime + timedelta(minutes=30)).isoformat(),
                    "timeZone": "Asia/Kolkata",
                },
            }

            service.events().patch(
                calendarId="primary",
                eventId=task.google_event_id,
                body=updated_event
            ).execute()

    except Exception as e:
        # Never block user edit for Google failures
        print("Google Calendar update failed:", e)


def _create_task_calendar_event(task, deadline_datetime):
    """Create a Google Calendar event for a newly-added task, if connected.

    Extracted verbatim from add_task. Best-effort: runs only when a deadline
    datetime exists and the user is connected to Google; a failure is logged and
    never blocks task creation. Persists the created event id on the task.
    """
    if not (
        deadline_datetime
        and current_user.google_access_token
        and current_user.google_refresh_token
    ):
        return

    try:
        service = build_calendar_service(current_user)

        event = {
            "summary": f"To-Do: {task.title}",
            "description": f"Priority: {task.priority}",
            "start": {
                "dateTime": deadline_datetime.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "end": {
                "dateTime": (deadline_datetime + timedelta(minutes=30)).isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 60},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }

        created_event = service.events().insert(
            calendarId="primary",
            body=event
        ).execute()

        task.google_event_id = created_event.get("id")
        db.session.commit()

    except Exception as e:
        # Do NOT crash app for calendar failures
        print("Google Calendar error:", e)


def _delete_task_calendar_event(task):
    """Delete the task's Google Calendar event, if one exists.

    Extracted verbatim from delete_task. Best-effort: a Google failure never
    blocks deletion.
    """
    if not (
        task.google_event_id
        and current_user.google_access_token
        and current_user.google_refresh_token
    ):
        return

    try:
        service = build_calendar_service(current_user)

        service.events().delete(
            calendarId="primary",
            eventId=task.google_event_id
        ).execute()

    except Exception as e:
        # Never block deletion if Google fails
        print("Google Calendar delete failed:", e)


# EDIT TASK
@tasks_bp.route('/edit/<int:task_id>', methods=['POST'])
@login_required
def edit_task(task_id):
    task = _authorize_task(task_id, 'edit')

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    priority = request.form.get('priority', 'Medium')
    deadline_str = request.form.get('deadline', '').strip()
    time_str = request.form.get('time_slot', '').strip()
    status = request.form.get('status', '').strip()
    assigned_to_raw = request.form.get('assigned_to', None)
    next_url = request.form.get('next')

    fallback_redirect = next_url or url_for('tasks.view_tasks')

    if not title:
        flash("Task title cannot be empty.", "danger")
        return redirect(fallback_redirect)

    if len(title) > 100:
        flash("Task title must be 100 characters or less.", "danger")
        return redirect(fallback_redirect)


    # PARSE DATE
    deadline = None
    if deadline_str:
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid date format.", "danger")
            return redirect(fallback_redirect)

    # PARSE TIME
    time_slot = None
    if time_str:
        try:
            time_slot = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            flash("Invalid time format.", "danger")
            return redirect(fallback_redirect)


    # VALIDATE ASSIGNEE
    # Done before any field is mutated: an invalid assignment must not leave the
    # task half-updated in the session, which the after-request activity logger
    # would then commit.
    #
    # The assignee must belong to the organization that owns this task's project.
    # Without this check any user id could be submitted, handing someone in an
    # unrelated organization a task that then renders on their calendar and
    # notifies them — see projects.add_task, which has always validated this.
    assignment_requested = False
    validated_assigned_to = None
    if task.project_id and assigned_to_raw is not None:
        assignment_requested = True
        cleaned = assigned_to_raw.strip()
        if cleaned:
            try:
                assigned_id = int(cleaned)
            except ValueError:
                flash('Invalid assignment.', 'danger')
                return redirect(fallback_redirect)

            project = Project.query.get(task.project_id)
            if not project or not OrgMember.query.filter_by(
                org_id=project.org_id, user_id=assigned_id
            ).first():
                flash('You can only assign tasks to members of this organization.', 'danger')
                return redirect(fallback_redirect)

            validated_assigned_to = assigned_id

    # Snapshot prior state so we can detect what actually changed and notify accordingly
    prev_assigned_to = task.assigned_to
    prev_status = task.status

    # UPDATE TASK

    task.title = title
    task.description = description if description else None
    task.priority = priority
    task.deadline = deadline
    task.time_slot = time_slot

    # Project-task fields — only meaningful when this is a project task
    if task.project_id:
        if status in ('Pending', 'Working', 'Completed'):
            _set_status(task, status)
        if assignment_requested:
            task.assigned_to = validated_assigned_to

    # Notify the relevant people about the edit (project tasks only).
    _notify_task_edit(task, prev_assigned_to, prev_status)

    db.session.commit()

    # UPDATE GOOGLE CALENDAR EVENT (IF EXISTS)
    _update_task_calendar_event(task, deadline, time_slot)

    flash("Task updated successfully.", "success")
    return redirect(fallback_redirect)



def _set_status(task, new_status):
    """Set a task's status and keep `completed_at` in sync (set on first
    completion, cleared if the task is reopened)."""
    task.status = new_status
    if new_status == 'Completed':
        if task.completed_at is None:
            task.completed_at = datetime.now(timezone.utc)
    else:
        task.completed_at = None


# TOGGLE TASK STATUS
@tasks_bp.route('/toggle/<int:task_id>', methods=['POST'])
@login_required
def toggle_status(task_id):
    task = _authorize_task(task_id, 'status')

    if task.status == 'Pending':
        _set_status(task, 'Working')
    elif task.status == 'Working':
        _set_status(task, 'Completed')
    else:
        _set_status(task, 'Pending')

    # Notify the task creator and assignee (excluding the person doing the toggle).
    # Only fires for project tasks — personal tasks have no audience.
    if task.project_id:
        actor_name = current_user.name or current_user.username
        link = url_for('projects.dashboard', project_id=task.project_id)
        notified = {current_user.id}
        if task.assigned_to and task.assigned_to not in notified:
            create_notification(
                task.assigned_to,
                f"{actor_name} moved '{task.title}' to {task.status}",
                link,
            )
            notified.add(task.assigned_to)
        if task.created_by and task.created_by not in notified:
            create_notification(
                task.created_by,
                f"{actor_name} moved your task '{task.title}' to {task.status}",
                link,
            )

    db.session.commit()
    next_url = request.form.get('next')
    return redirect(next_url or url_for('tasks.view_tasks'))


# DELETE TASK

@tasks_bp.route('/delete/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    task = _authorize_task(task_id, 'delete')

    
    # DELETE GOOGLE CALENDAR EVENT (IF EXISTS)
    _delete_task_calendar_event(task)

    
    # DELETE LOCAL TASK
    


        
    db.session.delete(task)
    db.session.commit()

    flash('Task deleted.', 'info')
    next_url = request.form.get('next')
    return redirect(next_url or url_for('tasks.view_tasks'))



# CLEAR ALL TASKS

@tasks_bp.route('/clear', methods=['POST'])
@login_required
def clear_tasks():
    # Only clear personal tasks; never wipe project tasks the user is involved in.
    Task.query.filter_by(user_id=current_user.id).filter(Task.project_id.is_(None)).delete(synchronize_session=False)
    db.session.commit()
    flash('All your tasks have been cleared.', 'info')
    return redirect(url_for('tasks.view_tasks'))


# -------------------------------------------------
# EXPORT TASKS AS CSV
# -------------------------------------------------
@tasks_bp.route('/export-csv')
@login_required
def export_csv():
    range_type = request.args.get('range', 'all')
    start_str = request.args.get('start', '').strip()
    end_str = request.args.get('end', '').strip()

    query = Task.query.filter_by(user_id=current_user.id).filter(Task.project_id.is_(None))

    today = date.today()

    if range_type == '7':
        since = today - timedelta(days=7)
        query = query.filter(Task.created_at >= datetime.combine(since, time(0, 0)))
    elif range_type == '15':
        since = today - timedelta(days=15)
        query = query.filter(Task.created_at >= datetime.combine(since, time(0, 0)))
    elif range_type == '30':
        since = today - timedelta(days=30)
        query = query.filter(Task.created_at >= datetime.combine(since, time(0, 0)))
    elif range_type == 'custom':
        try:
            if start_str:
                start_date = datetime.strptime(start_str, "%Y-%m-%d")
                query = query.filter(Task.created_at >= start_date)
            if end_str:
                end_date = datetime.strptime(end_str, "%Y-%m-%d")
                # Include the entire end day
                end_date = end_date.replace(hour=23, minute=59, second=59)
                query = query.filter(Task.created_at <= end_date)
        except ValueError:
            flash("Invalid date format for export.", "danger")
            return redirect(url_for('tasks.view_tasks'))

    tasks = query.order_by(Task.created_at.desc()).all()

    # Build CSV in memory
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['Title', 'Status', 'Priority', 'Deadline', 'Time', 'Created At'])

    for t in tasks:
        writer.writerow([
            t.title,
            t.status,
            t.priority,
            t.deadline.strftime('%d %b %Y') if t.deadline else '',
            t.time_slot.strftime('%I:%M %p') if t.time_slot else '',
            t.created_at.strftime('%d %b %Y %I:%M %p') if t.created_at else '',
        ])

    output = si.getvalue()
    si.close()

    filename = f"tasks_export_{today.strftime('%Y%m%d')}.csv"

    return Response(
        output,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename={filename}'
        }
    )
