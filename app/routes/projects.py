from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Organization, OrgMember, Project, Task, User, ActivityLog
from app.extensions import db
from app.utils import log_activity, create_notification

projects_bp = Blueprint('projects', __name__, url_prefix='/projects')

@projects_bp.route('/<org_slug>/create', methods=['GET', 'POST'])
@login_required
def create_project(org_slug):
    org = Organization.query.filter_by(slug=org_slug).first_or_404()
    
    # Verify membership
    membership = OrgMember.query.filter_by(org_id=org.id, user_id=current_user.id).first()
    if not membership:
        flash('You do not have permission to create projects here.', 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if not name:
            flash('Project name is required.', 'danger')
            return redirect(url_for('projects.create_project', org_slug=org_slug))
            
        new_project = Project(
            name=name,
            description=description,
            org_id=org.id,
            created_by=current_user.id
        )
        db.session.add(new_project)
        db.session.flush() # flush to get new_project.id
        
        log_activity(org.id, current_user.id, f"created project '{name}'", new_project.id)
        
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

    # Get recent activity for this project
    activities = ActivityLog.query.filter_by(project_id=project.id).order_by(ActivityLog.created_at.desc()).limit(15).all()

    is_admin = membership.role == 'Admin'

    return render_template('projects/dashboard.html',
                           project=project,
                           org=org,
                           pending_tasks=pending_tasks,
                           working_tasks=working_tasks,
                           completed_tasks=completed_tasks,
                           org_members=org_members,
                           activities=activities,
                           is_admin=is_admin)

@projects_bp.route('/<int:project_id>/task/add', methods=['POST'])
@login_required
def add_task(project_id):
    project = Project.query.get_or_404(project_id)
    org = project.organization
    
    # Verify membership
    membership = OrgMember.query.filter_by(org_id=org.id, user_id=current_user.id).first()
    if not membership:
        flash('Permission denied.', 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    title = request.form.get('title', '').strip()
    priority = request.form.get('priority', 'Medium')
    assigned_to = request.form.get('assigned_to')
    
    if not title:
        flash('Task title is required.', 'danger')
        return redirect(url_for('projects.dashboard', project_id=project.id))
        
    new_task = Task(
        title=title,
        priority=priority,
        project_id=project.id,
        user_id=current_user.id, # The owner concept still defaults to creator if unassigned
        created_by=current_user.id,
        assigned_to=int(assigned_to) if assigned_to else None,
        status='Pending'
    )
    
    db.session.add(new_task)
    
    log_activity(org.id, current_user.id, f"added task '{title}'", project.id)
    
    if new_task.assigned_to and new_task.assigned_to != current_user.id:
        create_notification(
            new_task.assigned_to,
            f"{current_user.name or current_user.username} assigned you a task: {title}",
            url_for('projects.dashboard', project_id=project.id)
        )
    
    db.session.commit()
    
    flash('Task added successfully.', 'success')
    return redirect(url_for('projects.dashboard', project_id=project.id))
