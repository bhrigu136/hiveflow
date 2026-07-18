from app.extensions import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import TSVECTOR
import secrets
import json

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
    # Set when status first becomes 'Completed' (cleared if reopened). Powers
    # velocity / cycle-time analytics.
    completed_at = db.Column(db.DateTime, nullable=True, index=True)

    # Google Calendar event tracking
    google_event_id = db.Column(db.String(255), nullable=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)

    # Phase 2 Additions
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True, index=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # AI Meeting Intelligence: the meeting whose action item produced this task
    source_meeting_id = db.Column(db.Integer, db.ForeignKey('meeting.id'), nullable=True, index=True)

    # Explicit relationships to fix AmbiguousForeignKeysError
    assignee = db.relationship('User', foreign_keys=[assigned_to], backref='assigned_tasks')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_tasks_group')
    source_meeting = db.relationship('Meeting', foreign_keys=[source_meeting_id],
                                     backref=db.backref('source_tasks', lazy='dynamic'))

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



# ── Phase 4: Calendar & Meeting Scheduling ──────────────────────────────────

class Meeting(db.Model):
    """A scheduled meeting booked on a team's shared calendar.

    Any member of the organization can book a timeslot, invite teammates, and
    the meeting links to a private Jitsi room (room_name). Optionally tied to a
    specific project. Per-attendee Google Calendar events are tracked on the
    MeetingAttendee rows so each person's event can be created/removed cleanly.
    """
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True, index=True)

    scheduled_for = db.Column(db.DateTime, nullable=False, index=True)
    duration_minutes = db.Column(db.Integer, default=30, nullable=False)

    room_name = db.Column(db.String(120), nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # ── AI Meeting Intelligence ─────────────────────────────────────────────
    # Populated after a meeting is transcribed + summarized. All nullable so
    # existing meetings are completely unaffected.
    transcript_full = db.Column(db.Text, nullable=True)        # assembled, speaker-labeled
    summary = db.Column(db.Text, nullable=True)
    _action_items = db.Column('action_items', db.Text, nullable=True)  # JSON list (see property)
    _decisions = db.Column('decisions', db.Text, nullable=True)        # JSON list
    # Lifecycle: none → recording → processing → ready (or error)
    intel_status = db.Column(db.String(20), default='none', nullable=False, index=True)
    summarized_at = db.Column(db.DateTime, nullable=True)
    summarizer_engine = db.Column(db.String(20), nullable=True)  # 'extractive' | 'llm'

    # Relationships
    organization = db.relationship('Organization', backref=db.backref('meetings', lazy='dynamic', cascade='all, delete-orphan'))
    project = db.relationship('Project', backref=db.backref('meetings', lazy='dynamic'))
    organizer = db.relationship('User', foreign_keys=[created_by])
    attendees = db.relationship('MeetingAttendee', backref='meeting', lazy='select', cascade='all, delete-orphan')

    @property
    def end_time(self):
        from datetime import timedelta
        return self.scheduled_for + timedelta(minutes=self.duration_minutes or 30)

    # action_items / decisions are stored as JSON text but exposed as lists.
    @property
    def action_items(self):
        return json.loads(self._action_items) if self._action_items else []

    @action_items.setter
    def action_items(self, value):
        self._action_items = json.dumps(value) if value is not None else None

    @property
    def decisions(self):
        return json.loads(self._decisions) if self._decisions else []

    @decisions.setter
    def decisions(self, value):
        self._decisions = json.dumps(value) if value is not None else None

    def __repr__(self):
        return f"<Meeting {self.title} @ {self.scheduled_for}>"


class MeetingAttendee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey('meeting.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    status = db.Column(db.String(20), default="Invited")  # Invited / Accepted / Declined

    # Per-attendee Google Calendar event id (so we can update/delete their copy)
    google_event_id = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint('meeting_id', 'user_id', name='uq_meeting_attendee'),
    )

    def __repr__(self):
        return f"<MeetingAttendee user={self.user_id} meeting={self.meeting_id} ({self.status})>"


class TranscriptSegment(db.Model):
    """One finalized snippet of speech captured during a meeting.

    Each participant's browser runs the Web Speech API on their own microphone
    and POSTs final segments here, tagged with their user_id and the time they
    started speaking. The full meeting transcript is assembled by ordering every
    segment across all speakers by `started_at`. `seq` is a per-client monotonic
    counter that, with the unique constraint, makes re-POSTed batches idempotent.
    """
    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey('meeting.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)

    text = db.Column(db.Text, nullable=False)
    started_at = db.Column(db.DateTime, nullable=False, index=True)  # when the speaker began (UTC)
    is_final = db.Column(db.Boolean, default=True, nullable=False)
    seq = db.Column(db.Integer, nullable=True)  # client monotonic counter (idempotency)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    meeting = db.relationship('Meeting', backref=db.backref('segments', lazy='dynamic', cascade='all, delete-orphan'))
    speaker = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint('meeting_id', 'user_id', 'seq', name='uq_segment_meeting_user_seq'),
    )

    def __repr__(self):
        return f"<TranscriptSegment m={self.meeting_id} u={self.user_id} seq={self.seq}>"


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user_rel = db.relationship('User', backref=db.backref('notifications', lazy='dynamic', cascade='all, delete-orphan'))


class LoginSession(db.Model):
    """One row per successful login — a record of a device/browser signed into
    an account. Powers the "Security / Your Devices" page so a user can see
    where their account is logged in, from which IP/location and device, when it
    was last active, and remotely log a device out (set revoked=True).
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)

    # Random opaque token stored in the Flask session cookie; identifies this
    # specific device session without exposing the row id.
    session_token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    ip_address = db.Column(db.String(64), nullable=True)
    location = db.Column(db.String(150), nullable=True)   # "Mumbai, India" or "Unknown"

    user_agent = db.Column(db.Text, nullable=True)        # raw UA string
    browser = db.Column(db.String(80), nullable=True)     # parsed, e.g. "Chrome"
    os = db.Column(db.String(80), nullable=True)          # parsed, e.g. "Windows"
    device = db.Column(db.String(40), nullable=True)      # "Desktop" / "Mobile" / "Tablet"

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    last_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    revoked = db.Column(db.Boolean, default=False, nullable=False, index=True)
    revoked_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('login_sessions', lazy='dynamic', cascade='all, delete-orphan'))

    @property
    def device_label(self) -> str:
        """Human-friendly one-line description, e.g. 'Chrome on Windows'."""
        b = self.browser or 'Unknown browser'
        o = self.os or 'Unknown OS'
        return f"{b} on {o}"

    def __repr__(self):
        return f"<LoginSession user={self.user_id} {self.device_label} revoked={self.revoked}>"


class ActivityLog(db.Model):
    """A trail of what each device did — page views and state-changing actions.
    Linked to a LoginSession so the Security page can show per-device activity
    ("what are they doing"). Best-effort: recorded after each request.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey('login_session.id'), nullable=True, index=True)

    action = db.Column(db.String(255), nullable=False)    # e.g. "Created task" / "Viewed tasks"
    method = db.Column(db.String(10), nullable=True)       # GET / POST / ...
    path = db.Column(db.String(255), nullable=True)        # request path
    ip_address = db.Column(db.String(64), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship('User', backref=db.backref('activity_logs', lazy='dynamic', cascade='all, delete-orphan'))
    session = db.relationship('LoginSession', backref=db.backref('activities', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f"<ActivityLog user={self.user_id} {self.action}>"


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
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=True, index=True)

    # Explicit relationships
    uploader = db.relationship('User', backref=db.backref('file_attachments', lazy='dynamic', cascade='all, delete-orphan'), foreign_keys=[uploaded_by])
    project_rel = db.relationship('Project', backref=db.backref('file_attachments', lazy='dynamic', cascade='all, delete-orphan'), foreign_keys=[project_id])
    task_rel = db.relationship('Task', backref=db.backref('file_attachments', lazy='dynamic', cascade='all, delete-orphan'), foreign_keys=[task_id])
    discussion_rel = db.relationship('Discussion', backref=db.backref('file_attachments', lazy='dynamic', cascade='all, delete-orphan'), foreign_keys=[discussion_id])
    document_rel = db.relationship('Document', backref=db.backref('file_attachments', lazy='dynamic', cascade='all, delete-orphan'), foreign_keys=[document_id])


# ── Phase 2: Team Docs / Wiki ────────────────────────────────────────────────

class Document(db.Model):
    """An org-scoped wiki page. Markdown is the source of truth (`content`); the
    sanitized HTML (`content_html`) is rendered on save and is what the viewer
    displays. Pages nest via `parent_id` to form a tree.
    """
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True, index=True)

    title = db.Column(db.String(255), nullable=False, default='Untitled')
    content = db.Column(db.Text, nullable=True)        # Markdown source of truth
    content_html = db.Column(db.Text, nullable=True)   # sanitized HTML cache (render on save)
    content_text = db.Column(db.Text, nullable=True)   # plain shadow for search / previews

    parent_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=True, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)  # soft delete

    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Full-text search vector, populated app-side on save. Renders as a real
    # tsvector on Postgres (FTS + GIN index); falls back to Text elsewhere so
    # the column always exists (e.g. SQLite in tests) and SELECTs never break.
    search_vector = db.Column(db.Text().with_variant(TSVECTOR(), 'postgresql'), nullable=True)

    organization = db.relationship('Organization', backref=db.backref('documents', lazy='dynamic', cascade='all, delete-orphan'))
    project = db.relationship('Project', backref=db.backref('documents', lazy='dynamic'))
    creator = db.relationship('User', foreign_keys=[created_by])
    editor = db.relationship('User', foreign_keys=[updated_by])
    parent = db.relationship('Document', remote_side=[id],
                             backref=db.backref('children', lazy='select',
                                                order_by='Document.sort_order, Document.id'))

    __table_args__ = (
        db.Index('ix_document_org_parent_sort', 'org_id', 'parent_id', 'sort_order'),
    )

    def __repr__(self):
        return f"<Document {self.id} {self.title!r}>"


class DocumentRevision(db.Model):
    """A point-in-time Markdown snapshot of a Document, written on each save.
    Only the last ~50 per document are kept (older ones pruned in the route)."""
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=True)
    content = db.Column(db.Text, nullable=True)  # Markdown snapshot
    edited_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    document = db.relationship('Document', backref=db.backref('revisions', lazy='dynamic', cascade='all, delete-orphan'))
    editor = db.relationship('User', foreign_keys=[edited_by])

    def __repr__(self):
        return f"<DocumentRevision doc={self.document_id} at={self.created_at}>"

