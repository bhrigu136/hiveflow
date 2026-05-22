from app.extensions import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
import secrets

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    profile_picture = db.Column(db.String(255), nullable=True, default='default.png')

    # Email verification
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    email_verify_token = db.Column(db.String(64), nullable=True)
    email_verify_expiry = db.Column(db.DateTime, nullable=True)

    # Password reset
    reset_code = db.Column(db.String(6), nullable=True)
    reset_code_expiry = db.Column(db.DateTime, nullable=True)

    # Google Calendar OAuth
    google_access_token = db.Column(db.Text, nullable=True)
    google_refresh_token = db.Column(db.Text, nullable=True)
    google_token_expiry = db.Column(db.DateTime, nullable=True)

    # Theme preference
    theme_preference = db.Column(db.String(20), default='light', nullable=False)

    tasks = db.relationship('Task', backref='user', lazy=True, foreign_keys='Task.user_id')

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def generate_verify_token(self) -> str:
        """Generate a secure email verification token (valid 24 hours)."""
        from datetime import timedelta
        token = secrets.token_urlsafe(32)
        self.email_verify_token = token
        self.email_verify_expiry = datetime.now(timezone.utc) + timedelta(hours=24)
        return token

    def get_recent_notifications(self, limit=10):
        from app.models import Notification
        return self.notifications.order_by(Notification.created_at.desc()).limit(limit).all()

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="Pending", index=True)

    priority = db.Column(db.String(20), default="Medium", index=True)
    deadline = db.Column(db.Date, nullable=True)
    time_slot = db.Column(db.Time, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Google Calendar event tracking
    google_event_id = db.Column(db.String(255), nullable=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)

    # Phase 2 Additions
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True, index=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Explicit relationships to fix AmbiguousForeignKeysError
    assignee = db.relationship('User', foreign_keys=[assigned_to], backref='assigned_tasks')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_tasks_group')

    def __repr__(self):
        return f"<Task {self.title} ({self.status})>"

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    organization = db.relationship('Organization', backref=db.backref('projects', lazy='dynamic', cascade='all, delete-orphan'))
    creator_user = db.relationship('User', foreign_keys=[created_by])
    tasks = db.relationship('Task', backref='project', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Project {self.name} in Org {self.org_id}>"

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    invite_code = db.Column(db.String(20), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Relationships
    creator = db.relationship('User', backref='created_orgs', foreign_keys=[created_by])
    members = db.relationship('OrgMember', backref='organization', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Organization {self.name}>"

class OrgMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    role = db.Column(db.String(20), default="Member") # Admin or Member
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', backref='org_memberships', foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint('org_id', 'user_id', name='uq_org_member'),
    )

    def __repr__(self):
        return f"<OrgMember {self.user.username} in Org {self.org_id}>"

# ── Phase 3: Collaboration ──────────────────────────────────────────────────

class Discussion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    creator = db.relationship('User', foreign_keys=[created_by])
    project = db.relationship('Project', backref=db.backref('discussions', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f"<Discussion {self.title}>"

class DiscussionComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    creator = db.relationship('User', foreign_keys=[created_by])
    discussion = db.relationship('Discussion', backref=db.backref('comments', lazy='dynamic', cascade='all, delete-orphan'))

class TaskComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    creator = db.relationship('User', foreign_keys=[created_by])
    task = db.relationship('Task', backref=db.backref('comments', lazy='dynamic', cascade='all, delete-orphan'))



class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user_rel = db.relationship('User', backref=db.backref('notifications', lazy='dynamic', cascade='all, delete-orphan'))


class FileAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    file_url = db.Column(db.String(512), nullable=False)
    file_size = db.Column(db.Integer, nullable=True) # in bytes
    mime_type = db.Column(db.String(100), nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Optional context scope
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True, index=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True, index=True)

    # Explicit relationships
    uploader = db.relationship('User', backref=db.backref('file_attachments', lazy='dynamic', cascade='all, delete-orphan'), foreign_keys=[uploaded_by])
    project_rel = db.relationship('Project', backref=db.backref('file_attachments', lazy='dynamic', cascade='all, delete-orphan'), foreign_keys=[project_id])
    task_rel = db.relationship('Task', backref=db.backref('file_attachments', lazy='dynamic', cascade='all, delete-orphan'), foreign_keys=[task_id])
    discussion_rel = db.relationship('Discussion', backref=db.backref('file_attachments', lazy='dynamic', cascade='all, delete-orphan'), foreign_keys=[discussion_id])

