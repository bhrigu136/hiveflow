# Flask-ToDo_App\app\routes\tasks.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, abort
from flask_login import login_required, current_user
from datetime import datetime, time, timedelta, date
from sqlalchemy import or_
from app.extensions import db
from app.models import Task, Project, OrgMember
from app.utils import log_activity

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os
import csv
import io

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")


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
    )



# ADD TASK

@tasks_bp.route('/add', methods=['POST'])
@login_required
def add_task():
    title = request.form.get('title', '').strip()
    priority = request.form.get('priority', 'Medium')
    deadline_str = request.form.get('deadline', '').strip()
    time_str = request.form.get('time_slot', '').strip()

    if not title:
        flash('Task title cannot be empty.', 'danger')
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
        priority=priority,
        deadline=deadline,
        time_slot=time_slot,
        user_id=current_user.id
    )

    db.session.add(task)
    db.session.commit()

    # CREATE GOOGLE CALENDAR EVENT (IF CONNECTED)
    if (
        deadline_datetime
        and current_user.google_access_token
        and current_user.google_refresh_token
    ):
        try:
            creds = Credentials(
                token=current_user.google_access_token,
                refresh_token=current_user.google_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
            )

            service = build("calendar", "v3", credentials=creds)

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
    print(
        f"[TASK AUTH] action={action} task_id={task_id} user_id={current_user.id} "
        f"org_id={project.org_id} role={membership.role!r} is_admin={is_admin} "
        f"assigned_to={task.assigned_to}"
    )

    if action == 'status':
        # Admin can toggle anything; a regular member can toggle only tasks assigned to them.
        if is_admin or task.assigned_to == current_user.id:
            return task
        _deny("not admin and not assignee")

    # 'edit' and 'delete' — admin only.
    if is_admin:
        return task
    _deny("not admin")


# EDIT TASK
@tasks_bp.route('/edit/<int:task_id>', methods=['POST'])
@login_required
def edit_task(task_id):
    task = _authorize_task(task_id, 'edit')

    title = request.form.get('title', '').strip()
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


    # UPDATE TASK

    task.title = title
    task.priority = priority
    task.deadline = deadline
    task.time_slot = time_slot

    # Project-task fields — only meaningful when this is a project task
    if task.project_id:
        if status in ('Pending', 'Working', 'Completed'):
            task.status = status
        if assigned_to_raw is not None:
            assigned_to_raw = assigned_to_raw.strip()
            if assigned_to_raw == '':
                task.assigned_to = None
            else:
                try:
                    task.assigned_to = int(assigned_to_raw)
                except ValueError:
                    pass

    db.session.commit()

    # UPDATE GOOGLE CALENDAR EVENT (IF EXISTS)
    if (
        task.google_event_id
        and current_user.google_access_token
        and current_user.google_refresh_token
        and (deadline or time_slot)
    ):
        try:
            # Rebuild datetime
            deadline_datetime = None
            if deadline and time_slot:
                deadline_datetime = datetime.combine(deadline, time_slot)
            elif deadline:
                deadline_datetime = datetime.combine(deadline, time(9, 0))

            if deadline_datetime:
                creds = Credentials(
                    token=current_user.google_access_token,
                    refresh_token=current_user.google_refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=GOOGLE_CLIENT_ID,
                    client_secret=GOOGLE_CLIENT_SECRET,
                )

                service = build("calendar", "v3", credentials=creds)

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

    flash("Task updated successfully.", "success")
    return redirect(fallback_redirect)



# TOGGLE TASK STATUS
@tasks_bp.route('/toggle/<int:task_id>', methods=['POST'])
@login_required
def toggle_status(task_id):
    task = _authorize_task(task_id, 'status')

    if task.status == 'Pending':
        task.status = 'Working'
    elif task.status == 'Working':
        task.status = 'Completed'
    else:
        task.status = 'Pending'

    if task.project_id:
        log_activity(task.project.org_id, current_user.id, f"moved task '{task.title}' to {task.status}", task.project_id)

    db.session.commit()
    next_url = request.form.get('next')
    return redirect(next_url or url_for('tasks.view_tasks'))


# DELETE TASK

@tasks_bp.route('/delete/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    task = _authorize_task(task_id, 'delete')

    
    # DELETE GOOGLE CALENDAR EVENT (IF EXISTS)

    if (
        task.google_event_id
        and current_user.google_access_token
        and current_user.google_refresh_token
    ):
        try:
            creds = Credentials(
                token=current_user.google_access_token,
                refresh_token=current_user.google_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
            )

            service = build("calendar", "v3", credentials=creds)

            service.events().delete(
                calendarId="primary",
                eventId=task.google_event_id
            ).execute()

        except Exception as e:
            # Never block deletion if Google fails
            print("Google Calendar delete failed:", e)

    
    # DELETE LOCAL TASK
    
    if task.project_id:
        log_activity(task.project.org_id, current_user.id, f"deleted task '{task.title}'", task.project_id)
        
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
