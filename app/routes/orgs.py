import re
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Organization, OrgMember, User
from app.extensions import db

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
