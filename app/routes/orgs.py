import re
import csv
import io
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from app.models import Organization, OrgMember, Project, Task
from app.extensions import db, limiter
from app.utils import create_notification
from app.services.analytics import org_analytics, member_task_breakdown

orgs_bp = Blueprint('orgs', __name__, url_prefix='/orgs')

def generate_slug(name):
    # Convert to lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    
    # Ensure uniqueness
    original_slug = slug
    counter = 1
    while Organization.query.filter_by(slug=slug).first() is not None:
        slug = f"{original_slug}-{counter}"
        counter += 1
        
    return slug

@orgs_bp.route('/')
@login_required
def list_orgs():
    # Get orgs where the current user is a member
    memberships = OrgMember.query.filter_by(user_id=current_user.id).all()
    orgs = [m.organization for m in memberships]
    return render_template('orgs/list.html', orgs=orgs)

@orgs_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_org():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        if not name:
            flash('Organization name is required.', 'danger')
            return redirect(url_for('orgs.create_org'))

        if Organization.query.filter_by(name=name).first():
            flash('An organization with this name already exists.', 'danger')
            return redirect(url_for('orgs.create_org'))

        slug = generate_slug(name)
        invite_code = secrets.token_urlsafe(6)

        new_org = Organization(
            name=name,
            slug=slug,
            description=description,
            invite_code=invite_code,
            created_by=current_user.id
        )
        db.session.add(new_org)
        db.session.flush() # Get the new org's ID

        # Add creator as Admin
        member = OrgMember(org_id=new_org.id, user_id=current_user.id, role="Admin")
        db.session.add(member)
        

        
        db.session.commit()
        flash(f'Organization "{name}" created successfully!', 'success')
        return redirect(url_for('orgs.dashboard', slug=new_org.slug))

    return render_template('orgs/create.html')

@orgs_bp.route('/join', methods=['POST'])
@login_required
@limiter.limit("5 per minute", error_message="Too many join attempts. Please wait.")
def join_org():
    invite_code = request.form.get('invite_code', '').strip()
    
    if not invite_code:
        flash('Invite code is required.', 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    org = Organization.query.filter_by(invite_code=invite_code).first()
    
    if not org:
        flash('Invalid invite code.', 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    # Check if already a member
    existing_member = OrgMember.query.filter_by(org_id=org.id, user_id=current_user.id).first()
    if existing_member:
        flash(f'You are already a member of {org.name}.', 'info')
        return redirect(url_for('orgs.dashboard', slug=org.slug))
        
    # Join org
    member = OrgMember(org_id=org.id, user_id=current_user.id, role="Member")
    db.session.add(member)

    # Notify every existing team member that someone new joined.
    # Existing members are queried BEFORE adding the new one above (the new row
    # isn't flushed yet, so this query returns the original member list).
    actor_name = current_user.name or current_user.username
    link = url_for('orgs.dashboard', slug=org.slug)
    existing_members = OrgMember.query.filter_by(org_id=org.id).all()
    for m in existing_members:
        if m.user_id == current_user.id:
            continue
        if m.user_id == org.created_by:
            # Personalised message for the team creator
            create_notification(
                m.user_id,
                f"{actor_name} joined your team '{org.name}'",
                link,
            )
        else:
            create_notification(
                m.user_id,
                f"{actor_name} joined the team '{org.name}'",
                link,
            )

    db.session.commit()
    
    flash(f'Successfully joined {org.name}!', 'success')
    return redirect(url_for('orgs.dashboard', slug=org.slug))

@orgs_bp.route('/<slug>')
@login_required
def dashboard(slug):
    org = Organization.query.filter_by(slug=slug).first_or_404()
    
    # Check if user is a member
    membership = OrgMember.query.filter_by(org_id=org.id, user_id=current_user.id).first()
    if not membership:
        flash('You do not have permission to view this organization.', 'danger')
        return redirect(url_for('orgs.list_orgs'))
        
    members = OrgMember.query.filter_by(org_id=org.id).all()
    
    return render_template('orgs/dashboard.html', org=org, membership=membership, members=members)

@orgs_bp.route('/<slug>/analytics')
@login_required
def analytics(slug):
    org = Organization.query.filter_by(slug=slug).first_or_404()
    
    # Check if user is a member AND an Admin
    membership = OrgMember.query.filter_by(org_id=org.id, user_id=current_user.id).first()
    if not membership or membership.role != 'Admin':
        flash('You do not have permission to view organization analytics.', 'danger')
        return redirect(url_for('orgs.dashboard', slug=org.slug))
        
    project_ids = [p.id for p in org.projects]
    tasks = Task.query.filter(Task.project_id.in_(project_ids)).all() if project_ids else []

    members_data = member_task_breakdown(org.members, tasks)

    stats = org_analytics(org.id)
    return render_template('orgs/analytics.html', org=org, members_data=members_data, stats=stats)


@orgs_bp.route('/<slug>/analytics/export.csv')
@login_required
def analytics_export(slug):
    org = Organization.query.filter_by(slug=slug).first_or_404()
    membership = OrgMember.query.filter_by(org_id=org.id, user_id=current_user.id).first()
    if not membership or membership.role != 'Admin':
        flash('You do not have permission to export analytics.', 'danger')
        return redirect(url_for('orgs.dashboard', slug=org.slug))

    stats = org_analytics(org.id)
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
                    headers={'Content-Disposition': f'attachment; filename={org.slug}-analytics.csv'})
