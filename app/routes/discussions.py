from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Project, Discussion, DiscussionComment, Task, TaskComment, OrgMember
from app.extensions import db

discussions_bp = Blueprint('discussions', __name__)

def check_project_access(project):
    """Helper to check if current_user is in the project's organization."""
    member = OrgMember.query.filter_by(org_id=project.org_id, user_id=current_user.id).first()
    return member is not None

# ── Project Discussions ──────────────────────────────────────────────

@discussions_bp.route('/projects/<int:project_id>/discussions')
@login_required
def list_discussions(project_id):
    project = Project.query.get_or_404(project_id)
    if not check_project_access(project):
        flash("You don't have access to this project's discussions.", 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    discussions = Discussion.query.filter_by(project_id=project.id).order_by(Discussion.created_at.desc()).all()
    return render_template('discussions/list.html', project=project, discussions=discussions)

@discussions_bp.route('/projects/<int:project_id>/discussions/create', methods=['POST'])
@login_required
def create_discussion(project_id):
    project = Project.query.get_or_404(project_id)
    if not check_project_access(project):
        flash("Access denied.", 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    
    if not title or not content:
        flash("Title and content are required.", 'danger')
        return redirect(url_for('discussions.list_discussions', project_id=project.id))
        
    new_discussion = Discussion(
        title=title,
        content=content,
        project_id=project.id,
        created_by=current_user.id
    )
    db.session.add(new_discussion)
    db.session.commit()
    
    flash("Discussion created successfully.", 'success')
    return redirect(url_for('discussions.view_discussion', discussion_id=new_discussion.id))

@discussions_bp.route('/discussions/<int:discussion_id>')
@login_required
def view_discussion(discussion_id):
    discussion = Discussion.query.get_or_404(discussion_id)
    if not check_project_access(discussion.project):
        flash("Access denied.", 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    comments = DiscussionComment.query.filter_by(discussion_id=discussion.id).order_by(DiscussionComment.created_at.asc()).all()
    return render_template('discussions/view.html', discussion=discussion, comments=comments)

@discussions_bp.route('/discussions/<int:discussion_id>/comment', methods=['POST'])
@login_required
def add_discussion_comment(discussion_id):
    discussion = Discussion.query.get_or_404(discussion_id)
    if not check_project_access(discussion.project):
        flash("Access denied.", 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    content = request.form.get('content', '').strip()
    if not content:
        flash("Comment cannot be empty.", 'danger')
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id))
        
    comment = DiscussionComment(
        content=content,
        discussion_id=discussion.id,
        created_by=current_user.id
    )
    db.session.add(comment)
    db.session.commit()
    
    return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id))

# ── Task Comments ──────────────────────────────────────────────────

@discussions_bp.route('/tasks/<int:task_id>/comment', methods=['POST'])
@login_required
def add_task_comment(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Check access. If it's a team task, check org. If personal, check user_id.
    if task.project_id:
        if not check_project_access(task.project):
            flash("Access denied.", 'danger')
            return redirect(url_for('orgs.list_orgs'))
    else:
        if task.user_id != current_user.id:
            flash("Access denied.", 'danger')
            return redirect(url_for('tasks.view_tasks'))
            
    content = request.form.get('content', '').strip()
    if not content:
        flash("Comment cannot be empty.", 'danger')
    else:
        comment = TaskComment(
            content=content,
            task_id=task.id,
            created_by=current_user.id
        )
        db.session.add(comment)
        db.session.commit()
        
    # Redirect back to wherever we came from
    next_url = request.form.get('next')
    return redirect(next_url or request.referrer or url_for('tasks.view_tasks'))
