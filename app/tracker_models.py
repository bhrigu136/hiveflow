"""
Growth Plan Builder — Database Models
======================================
Flexible, reusable models that power any type of growth/tracking plan.
The 90-Day Career Growth Tracker is one template built on top of these.
"""

from app.extensions import db
from datetime import datetime, timezone
import json


class GrowthPlan(db.Model):
    """Master plan — one per user per challenge."""
    __tablename__ = 'growth_plan'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    template_type = db.Column(db.String(50), nullable=False, default='blank')  # 'career_90day', 'blank', etc.
    duration_days = db.Column(db.Integer, nullable=False, default=90)
    start_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # JSON config — stores goals, weekly planner, daily checkbox definitions, etc.
    _config = db.Column('config', db.Text, nullable=True)

    # Relationships
    owner = db.relationship('User', backref=db.backref('growth_plans', lazy='dynamic'))
    daily_logs = db.relationship('DailyLog', backref='plan', lazy='dynamic', cascade='all, delete-orphan')
    topic_entries = db.relationship('TopicEntry', backref='plan', lazy='dynamic', cascade='all, delete-orphan')
    job_applications = db.relationship('JobApplication', backref='plan', lazy='dynamic', cascade='all, delete-orphan')
    interview_records = db.relationship('InterviewRecord', backref='plan', lazy='dynamic', cascade='all, delete-orphan')
    skill_ratings = db.relationship('SkillRating', backref='plan', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def config(self):
        if self._config:
            return json.loads(self._config)
        return {}

    @config.setter
    def config(self, value):
        self._config = json.dumps(value)

    @property
    def modules(self):
        """Which feature sections this plan shows (tabs + dashboard cards).

        New plans store an explicit `modules` list in config. Plans created
        before that existed fall back to a sensible default for their template
        so a 'blank' plan never shows career-only sections (jobs, DSA, etc.).
        """
        cfg = self.config
        mods = cfg.get('modules')
        if mods is not None:
            return mods
        if self.template_type == 'career_90day':
            return ['topics', 'jobs', 'interviews', 'weekly', 'skills', 'goals']
        # Generic/blank plans: just the universal tracking sections.
        mods = ['weekly', 'goals']
        if cfg.get('topic_categories'):
            mods = ['topics'] + mods
        return mods

    def __repr__(self):
        return f"<GrowthPlan {self.name} ({self.template_type})>"


class DailyLog(db.Model):
    """One row per day in the challenge."""
    __tablename__ = 'daily_log'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('growth_plan.id'), nullable=False, index=True)
    day_number = db.Column(db.Integer, nullable=False)  # 1–90
    date = db.Column(db.Date, nullable=False)

    # Flexible checkboxes — stored as JSON: {"dsa": true, "sql": false, ...}
    _checkboxes = db.Column('checkboxes', db.Text, default='{}')

    # Flexible metrics — stored as JSON: {"leetcode_solved": 3, "study_hours": 4, ...}
    _metrics = db.Column('metrics', db.Text, default='{}')

    notes = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('plan_id', 'day_number', name='uq_daily_log_plan_day'),
    )

    @property
    def checkboxes(self):
        if self._checkboxes:
            return json.loads(self._checkboxes)
        return {}

    @checkboxes.setter
    def checkboxes(self, value):
        self._checkboxes = json.dumps(value)

    @property
    def metrics(self):
        if self._metrics:
            return json.loads(self._metrics)
        return {}

    @metrics.setter
    def metrics(self, value):
        self._metrics = json.dumps(value)

    @property
    def completion_pct(self):
        """Auto-calculate daily completion % from checkboxes."""
        cb = self.checkboxes
        if not cb:
            return 0
        total = len(cb)
        done = sum(1 for v in cb.values() if v)
        return int((done / total) * 100) if total else 0

    def __repr__(self):
        return f"<DailyLog Day {self.day_number}>"


class TopicEntry(db.Model):
    """Generic topic tracker — handles DSA, SQL, Data Science, or any custom category."""
    __tablename__ = 'topic_entry'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('growth_plan.id'), nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False, index=True)  # 'dsa', 'sql', 'datascience', etc.
    topic = db.Column(db.String(200), nullable=False)
    target_count = db.Column(db.Integer, default=0)
    solved_count = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0)

    @property
    def progress_pct(self):
        if self.target_count and self.target_count > 0:
            return min(100, int((self.solved_count / self.target_count) * 100))
        return 0

    def __repr__(self):
        return f"<TopicEntry {self.category}/{self.topic}>"


class JobApplication(db.Model):
    """Job application tracking with structured columns."""
    __tablename__ = 'job_application'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('growth_plan.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    company = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(200), nullable=False)
    platform = db.Column(db.String(100), nullable=True)  # LinkedIn, Naukri, etc.
    status = db.Column(db.String(50), default='Applied')  # Applied, Interview, Rejected, Offered
    interview_date = db.Column(db.Date, nullable=True)
    result = db.Column(db.String(50), nullable=True)  # Pending, Selected, Rejected
    salary_offered = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<JobApplication {self.company} - {self.role}>"


class InterviewRecord(db.Model):
    """Interview tracking with performance ratings."""
    __tablename__ = 'interview_record'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('growth_plan.id'), nullable=False, index=True)
    company = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date, nullable=False)
    round_name = db.Column(db.String(100), nullable=True)  # Phone Screen, Technical, HR, etc.
    questions_asked = db.Column(db.Text, nullable=True)
    performance_rating = db.Column(db.Integer, nullable=True)  # 1–5
    weak_areas = db.Column(db.Text, nullable=True)
    result = db.Column(db.String(50), nullable=True)  # Passed, Failed, Pending
    followup_required = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<InterviewRecord {self.company} - {self.round_name}>"


class SkillRating(db.Model):
    """Skill matrix ratings (1–10) for radar chart."""
    __tablename__ = 'skill_rating'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('growth_plan.id'), nullable=False, index=True)
    skill_name = db.Column(db.String(100), nullable=False)
    rating = db.Column(db.Integer, default=1)  # 1–10
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('plan_id', 'skill_name', name='uq_skill_rating_plan_skill'),
    )

    def __repr__(self):
        return f"<SkillRating {self.skill_name}: {self.rating}/10>"
