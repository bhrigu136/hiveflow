from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.models import Project, Discussion, DiscussionComment, Task, TaskComment
from app.extensions import db
from app.utils import create_notification, notify_org_members
from app.authz import check_project_access

discussions_bp = Blueprint('discussions', __name__)

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

    if len(title) > 200:
        flash("Discussion title must be 200 characters or less.", 'danger')
        return redirect(url_for('discussions.list_discussions', project_id=project.id))

    if len(content) > 10000:
        flash("Discussion content must be 10,000 characters or less.", 'danger')
        return redirect(url_for('discussions.list_discussions', project_id=project.id))

    new_discussion = Discussion(
        title=title,
        content=content,
        project_id=project.id,
        created_by=current_user.id
    )
    db.session.add(new_discussion)
    

    
    # Notify all other org members
    notify_org_members(
        project.org_id,
        f"{current_user.name or current_user.username} started a new discussion: {title}",
        url_for('discussions.list_discussions', project_id=project.id),
        exclude_user_id=current_user.id,
    )

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
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not check_project_access(discussion.project):
        if is_ajax:
            return jsonify({'error': 'access denied'}), 403
        flash("Access denied.", 'danger')
        return redirect(url_for('orgs.list_orgs'))

    content = request.form.get('content', '').strip()
    if not content:
        if is_ajax:
            return jsonify({'error': 'Comment cannot be empty.'}), 400
        flash("Comment cannot be empty.", 'danger')
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id))

    if len(content) > 5000:
        if is_ajax:
            return jsonify({'error': 'Comment must be 5,000 characters or less.'}), 400
        flash("Comment must be 5,000 characters or less.", 'danger')
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id))

    comment = DiscussionComment(
        content=content,
        discussion_id=discussion.id,
        created_by=current_user.id
    )
    db.session.add(comment)

    # Notify all other org members
    notify_org_members(
        discussion.project.org_id,
        f"{current_user.name or current_user.username} commented on discussion '{discussion.title}'",
        url_for('discussions.view_discussion', discussion_id=discussion.id),
        exclude_user_id=current_user.id,
    )

    db.session.commit()

    # Trigger WebSocket Push Event for real-time instant rendering
    from app.extensions import get_pusher
    pusher_client = get_pusher()
    if pusher_client:
        try:
            pusher_client.trigger(
                f"project-{discussion.project.id}",
                "new-comment",
                {
                    'discussion_id': discussion.id,
                    'comment': _comment_to_dict(comment)
                }
            )
        except Exception as e:
            # Broadcast is best-effort — the comment is already saved. Broad
            # catch is intentional so a Pusher outage never breaks posting; the
            # failure is logged rather than swallowed silently.
            current_app.logger.warning(
                f'[pusher] new-comment broadcast failed for discussion '
                f'{discussion.id}: {type(e).__name__}: {e}'
            )

    if is_ajax:
        return jsonify({'ok': True, 'comment': _comment_to_dict(comment)})
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
    elif len(content) > 5000:
        flash("Comment must be 5,000 characters or less.", 'danger')
    else:
        comment = TaskComment(
            content=content,
            task_id=task.id,
            created_by=current_user.id
        )
        db.session.add(comment)
        
        if task.project_id:

            
            notified_users = set()
            if task.assigned_to and task.assigned_to != current_user.id:
                create_notification(task.assigned_to, f"{current_user.name or current_user.username} commented on your assigned task: {task.title}", url_for('projects.dashboard', project_id=task.project_id))
                notified_users.add(task.assigned_to)
                
            if task.created_by and task.created_by != current_user.id and task.created_by not in notified_users:
                create_notification(task.created_by, f"{current_user.name or current_user.username} commented on a task you created: {task.title}", url_for('projects.dashboard', project_id=task.project_id))
            
        db.session.commit()

        # Trigger WebSocket event if part of a project
        if task.project_id:
            from app.extensions import get_pusher
            pusher_client = get_pusher()
            if pusher_client:
                try:
                    pusher_client.trigger(
                        f"project-{task.project_id}",
                        "new-task-comment",
                        {
                            'task_id': task.id,
                            'comment': _comment_to_dict(comment)
                        }
                    )
                except Exception as e:
                    # Best-effort broadcast; the comment is already saved.
                    current_app.logger.warning(
                        f'[pusher] new-task-comment broadcast failed for task '
                        f'{task.id}: {type(e).__name__}: {e}'
                    )
        
    # Redirect back to wherever we came from
    next_url = request.form.get('next')
    return redirect(next_url or request.referrer or url_for('tasks.view_tasks'))


# ── Live-update polling endpoints (JSON) ──────────────────────────────

def _comment_to_dict(c):
    creator_name = c.creator.name if c.creator and c.creator.name else (c.creator.username if c.creator else 'Unknown')
    return {
        'id': c.id,
        'content': c.content,
        'creator_name': creator_name,
        'creator_initial': creator_name[0].upper() if creator_name else '?',
        'created_by': c.created_by,
        'created_at_iso': c.created_at.strftime('%Y-%m-%dT%H:%M:%SZ') if c.created_at else '',
        'created_at_short': c.created_at.strftime('%b %d, %I:%M %p') if c.created_at else '',
    }


@discussions_bp.route('/api/discussions/<int:discussion_id>/comments')
@login_required
def api_discussion_comments(discussion_id):
    """Return discussion comments newer than ?since_id=N (default 0).

    Used by the discussion view page to poll for new chat messages so members
    don't have to refresh.
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    if not check_project_access(discussion.project):
        return jsonify({'error': 'access denied'}), 403

    try:
        since_id = int(request.args.get('since_id', 0))
    except (TypeError, ValueError):
        since_id = 0

    new_comments = (
        DiscussionComment.query
        .filter_by(discussion_id=discussion.id)
        .filter(DiscussionComment.id > since_id)
        .order_by(DiscussionComment.created_at.asc())
        .all()
    )

    last_id = new_comments[-1].id if new_comments else since_id
    return jsonify({
        'last_id': last_id,
        'comments': [_comment_to_dict(c) for c in new_comments],
        'current_user_id': current_user.id,
    })


@discussions_bp.route('/api/projects/<int:project_id>/state')
@login_required
def api_project_state(project_id):
    """Return a fingerprint of the project's task board + new discussions.

    The dashboard polls this; if the fingerprint differs from the one captured
    at page load, the page soft-refreshes so everyone sees task moves, new
    assignments, and new discussions without manual reload.
    """
    project = Project.query.get_or_404(project_id)
    if not check_project_access(project):
        return jsonify({'error': 'access denied'}), 403

    tasks = Task.query.filter_by(project_id=project.id).all()
    # Build a deterministic fingerprint covering everything visible on the board.
    parts = []
    for t in sorted(tasks, key=lambda x: x.id):
        parts.append(
            f"{t.id}:{t.status}:{t.priority}:{t.assigned_to or 0}:"
            f"{t.title}:{t.comments.count()}"
        )
    discussion_count = Discussion.query.filter_by(project_id=project.id).count()
    parts.append(f"d:{discussion_count}")
    fingerprint = str(hash('|'.join(parts)))

    return jsonify({
        'fingerprint': fingerprint,
        'task_count': len(tasks),
        'discussion_count': discussion_count,
    })


@discussions_bp.route('/api/projects/<int:project_id>/discussions/state')
@login_required
def api_discussions_state(project_id):
    """Return the latest discussion ID for the project; the list page polls
    this to detect new discussions without a refresh."""
    project = Project.query.get_or_404(project_id)
    if not check_project_access(project):
        return jsonify({'error': 'access denied'}), 403

    latest = (
        Discussion.query
        .filter_by(project_id=project.id)
        .order_by(Discussion.id.desc())
        .first()
    )
    return jsonify({
        'latest_id': latest.id if latest else 0,
        'count': Discussion.query.filter_by(project_id=project.id).count(),
    })
