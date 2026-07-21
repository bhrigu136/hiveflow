import csv
import io
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, g
from flask_login import login_required, current_user
from app.models import OrgMember, Project, Task
from app.extensions import db
from app.utils import create_notification
from app.services.analytics import project_analytics, member_task_breakdown
from app.authz import (require_org_member, require_org_admin,
                       by_slug, by_project, redirect_flash)

projects_bp = Blueprint('projects', __name__, url_prefix='/projects')

@projects_bp.route('/<org_slug>/create', methods=['GET', 'POST'])
@login_required
@require_org_member(by_slug('org_slug'), redirect_flash(
    'orgs.list_orgs', 'You do not have permission to create projects here.'))
def create_project(org_slug):
    org = g.authz_obj

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if not name:
            flash('Project name is required.', 'danger')
            return redirect(url_for('projects.create_project', org_slug=org_slug))

        if len(name) > 100:
            flash('Project name must be 100 characters or less.', 'danger')
            return redirect(url_for('projects.create_project', org_slug=org_slug))

        if len(description) > 2000:
            flash('Project description must be 2000 characters or less.', 'danger')
            return redirect(url_for('projects.create_project', org_slug=org_slug))

        new_project = Project(
            name=name,
            description=description,
            org_id=org.id,
            created_by=current_user.id
        )
        db.session.add(new_project)
        db.session.flush() # flush to get new_project.id
        

        
        db.session.commit()
        
        flash(f'Project "{name}" created successfully!', 'success')
        return redirect(url_for('orgs.dashboard', slug=org.slug))
        
    return render_template('projects/create.html', org=org)

@projects_bp.route('/<int:project_id>')
@login_required
def dashboard(project_id):
    project = Project.query.get_or_404(project_id)
    org = project.organization
    
    # Verify membership
    membership = OrgMember.query.filter_by(org_id=org.id, user_id=current_user.id).first()
    if not membership:
        flash('You do not have permission to view this project.', 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    # Get tasks for this project
    tasks = Task.query.filter_by(project_id=project.id).all()
    
    # Separate tasks by status for a Kanban view
    pending_tasks = [t for t in tasks if t.status == 'Pending']
    working_tasks = [t for t in tasks if t.status == 'Working']
    completed_tasks = [t for t in tasks if t.status == 'Completed']
    
    # Get organization members for task assignment
    org_members = OrgMember.query.filter_by(org_id=org.id).all()



    is_admin = membership.role == 'Admin'

    return render_template('projects/dashboard.html',
                           project=project,
                           org=org,
                           pending_tasks=pending_tasks,
                           working_tasks=working_tasks,
                           completed_tasks=completed_tasks,
                           org_members=org_members,
                           is_admin=is_admin)

@projects_bp.route('/<int:project_id>/task/add', methods=['POST'])
@login_required
@require_org_member(by_project(),
                    redirect_flash('orgs.list_orgs', 'Permission denied.'))
def add_task(project_id):
    project = g.authz_obj
    org = project.organization

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    priority = request.form.get('priority', 'Medium')
    assigned_to = request.form.get('assigned_to')
    
    if not title:
        flash('Task title is required.', 'danger')
        return redirect(url_for('projects.dashboard', project_id=project.id))

    if len(title) > 100:
        flash('Task title must be 100 characters or less.', 'danger')
        return redirect(url_for('projects.dashboard', project_id=project.id))

    if description and len(description) > 5000:
        flash('Task description must be 5000 characters or less.', 'danger')
        return redirect(url_for('projects.dashboard', project_id=project.id))

    # Validate that the assigned user is actually a member of this org
    validated_assigned_to = None
    if assigned_to:
        try:
            assigned_id = int(assigned_to)
        except (ValueError, TypeError):
            flash('Invalid assignment.', 'danger')
            return redirect(url_for('projects.dashboard', project_id=project.id))
        assignee_membership = OrgMember.query.filter_by(
            org_id=org.id, user_id=assigned_id
        ).first()
        if not assignee_membership:
            flash('You can only assign tasks to members of this organization.', 'danger')
            return redirect(url_for('projects.dashboard', project_id=project.id))
        validated_assigned_to = assigned_id

    new_task = Task(
        title=title,
        description=description if description else None,
        priority=priority,
        project_id=project.id,
        user_id=current_user.id,
        created_by=current_user.id,
        assigned_to=validated_assigned_to,
        status='Pending'
    )
    
    db.session.add(new_task)
    

    if new_task.assigned_to and new_task.assigned_to != current_user.id:
        create_notification(
            new_task.assigned_to,
            f"{current_user.name or current_user.username} assigned you a task: {title}",
            url_for('projects.dashboard', project_id=project.id)
        )
    
    db.session.commit()
    
    flash('Task added successfully.', 'success')
    return redirect(url_for('projects.dashboard', project_id=project.id))

@projects_bp.route('/<int:project_id>/analytics')
@login_required
@require_org_admin(by_project(), redirect_flash(
    'projects.dashboard', 'You do not have permission to view project analytics.',
    values=lambda a: {'project_id': a.obj.id}))
def analytics(project_id):
    project = g.authz_obj
    org = project.organization

    tasks = Task.query.filter_by(project_id=project.id).all()

    members_data = member_task_breakdown(org.members, tasks)

    stats = project_analytics(project.id)
    return render_template('projects/analytics.html', project=project, org=org,
                           members_data=members_data, stats=stats)


@projects_bp.route('/<int:project_id>/analytics/export.csv')
@login_required
@require_org_admin(by_project(), redirect_flash(
    'projects.dashboard', 'You do not have permission to export analytics.',
    values=lambda a: {'project_id': a.obj.id}))
def analytics_export(project_id):
    project = g.authz_obj
    org = project.organization

    stats = project_analytics(project.id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Metric', 'Value'])
    for label, key in (('Total tasks', 'total'), ('Completed', 'completed'),
                       ('In progress', 'working'), ('Pending', 'pending'),
                       ('Overdue', 'overdue'), ('Completion rate %', 'completion_rate')):
        writer.writerow([label, stats['totals'][key]])
    writer.writerow([])
    writer.writerow(['Member', 'Assigned', 'Completed'])
    for m in stats['members']:
        writer.writerow([m['name'], m['total'], m['completed']])

    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=project-{project.id}-analytics.csv'})
