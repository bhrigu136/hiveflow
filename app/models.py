from app.extensions import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)

    # Password reset
    reset_code = db.Column(db.String(6), nullable=True)
    reset_code_expiry = db.Column(db.DateTime, nullable=True)

    # Google Calendar OAuth
    google_access_token = db.Column(db.Text, nullable=True)
    google_refresh_token = db.Column(db.Text, nullable=True)
    google_token_expiry = db.Column(db.DateTime, nullable=True)

    tasks = db.relationship('Task', backref='user', lazy=True, foreign_keys='Task.user_id')

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
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
