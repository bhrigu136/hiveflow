"""
Growth Plan Builder — Routes
==============================
Blueprint handling all tracker pages: plans list, dashboard, daily log,
topic trackers, job applications, interviews, weekly planner, skill matrix, goals.
"""

import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from app.extensions import db
from app.tracker_models import (
    GrowthPlan, DailyLog, TopicEntry,
    JobApplication, InterviewRecord, SkillRating,
)


def _make_key(label, existing_keys):
    """Turn a human label into a stable, unique config key (e.g. 'Morning Yoga' -> 'morning_yoga')."""
    base = re.sub(r'[^a-z0-9]+', '_', (label or '').lower()).strip('_') or 'field'
    key, i = base, 2
    while key in existing_keys:
        key = f'{base}_{i}'
        i += 1
    return key

tracker_bp = Blueprint('tracker', __name__, url_prefix='/tracker')


# ─── Template Seed Data ────────────────────────────────────────────────────────

CAREER_90DAY_DSA_TOPICS = [
    ("Arrays", 15), ("Strings", 12), ("Hash Maps", 12), ("Linked Lists", 10),
    ("Stacks", 8), ("Queues", 8), ("Trees", 12), ("BST", 8),
    ("Heaps", 8), ("Recursion", 10), ("Backtracking", 10),
    ("Graphs", 15), ("Dynamic Programming", 22),
]

CAREER_90DAY_SQL_TOPICS = [
    ("Basic Queries", 15), ("Joins", 15), ("Group By", 10),
    ("Aggregations", 10), ("Subqueries", 10), ("CTEs", 10),
    ("Window Functions", 12), ("Case Studies", 10), ("Interview Questions", 8),
]

CAREER_90DAY_DS_TOPICS = [
    ("NumPy", 100), ("Pandas", 100), ("Data Cleaning", 100),
    ("EDA", 100), ("Visualization", 100), ("Statistics", 100),
    ("Machine Learning Basics", 100), ("Linear Regression", 100),
    ("Logistic Regression", 100), ("Random Forest", 100),
    ("Project Development", 100),
]

CAREER_90DAY_SKILLS = [
    "Python", "SQL", "DSA", "Next.js", "React", "TypeScript",
    "APIs", "Database Design", "Data Science", "Machine Learning",
    "Communication", "Interview Skills",
]

CAREER_90DAY_WEEKLY_PLAN = [
    {"weeks": "1–2", "topics": ["Arrays", "Strings", "NumPy"]},
    {"weeks": "3–4", "topics": ["Hash Maps", "Linked Lists", "Pandas"]},
    {"weeks": "5–6", "topics": ["Stacks", "Queues", "Data Cleaning"]},
    {"weeks": "7–8", "topics": ["Trees", "BST", "EDA"]},
    {"weeks": "9–10", "topics": ["Graphs", "SQL Advanced", "Machine Learning"]},
    {"weeks": "11–12", "topics": ["Dynamic Programming", "Interview Preparation", "Project Building"]},
    {"weeks": "13", "topics": ["Revision", "Mock Interviews", "Resume Improvement"]},
]

CAREER_90DAY_GOALS = {
    "primary": "Get a Software Engineer, Next.js Developer, Full Stack Developer, Data Analyst, or Data Science role within 90 days.",
    "metrics": [
        {"name": "DSA Problems Solved", "target": 150, "source": "dsa"},
        {"name": "SQL Questions Solved", "target": 100, "source": "sql"},
        {"name": "Job Applications Submitted", "target": 300, "source": "jobs"},
        {"name": "Interviews Attended", "target": 10, "source": "interviews"},
        {"name": "Data Science Project", "target": 1, "source": "ds_project"},
        {"name": "Next.js Expertise Improved", "target": 100, "source": "skill_nextjs"},
        {"name": "Resume & Portfolio Updated", "target": 100, "source": "manual"},
    ],
}

CAREER_90DAY_DAILY_CHECKBOXES = [
    {"key": "dsa", "label": "DSA Completed"},
    {"key": "sql", "label": "SQL Completed"},
    {"key": "nextjs", "label": "Next.js Learning"},
    {"key": "datascience", "label": "Data Science Learning"},
]

CAREER_90DAY_DAILY_METRICS = [
    {"key": "jobs_submitted", "label": "Job Applications Submitted", "type": "number"},
    {"key": "leetcode_solved", "label": "LeetCode Problems Solved", "type": "number"},
    {"key": "study_hours", "label": "Study Hours", "type": "number"},
]


# ─── Helper: Ensure plan belongs to current user ───────────────────────────────

def _get_plan_or_404(plan_id):
    plan = GrowthPlan.query.get_or_404(plan_id)
    if plan.user_id != current_user.id:
        abort(404)
    return plan


def _today_day_number(plan):
    """Day number (1-based) corresponding to today. Can be <1 or >duration."""
    return (date.today() - plan.start_date).days + 1


def _is_future_day(plan, day_number):
    """A day is locked if it hasn't arrived yet — you can't log progress early."""
    return day_number > _today_day_number(plan)


def _require_module(plan, name):
    """Redirect to the dashboard if the plan doesn't include this section."""
    if name not in plan.modules:
        flash('That section is not part of this plan.', 'info')
        return redirect(url_for('tracker.dashboard', plan_id=plan.id))
    return None


def _compute_dashboard_stats(plan):
    """Compute all dashboard statistics for a plan."""
    today = date.today()
    days_elapsed = (today - plan.start_date).days + 1
    days_completed_count = min(days_elapsed, plan.duration_days)
    if days_completed_count < 0:
        days_completed_count = 0

    # Daily logs
    logs = DailyLog.query.filter_by(plan_id=plan.id).order_by(DailyLog.day_number).all()
    logs_by_day = {log.day_number: log for log in logs}

    # Count days with at least one checkbox done
    active_days = sum(1 for log in logs if any(log.checkboxes.values()))

    # Streaks
    current_streak = 0
    longest_streak = 0
    temp_streak = 0
    for day_num in range(1, min(days_completed_count, plan.duration_days) + 1):
        log = logs_by_day.get(day_num)
        if log and any(log.checkboxes.values()):
            temp_streak += 1
            longest_streak = max(longest_streak, temp_streak)
        else:
            temp_streak = 0
    current_streak = temp_streak

    # Overall completion
    overall_pct = int((active_days / plan.duration_days) * 100) if plan.duration_days else 0

    config = plan.config
    modules = plan.modules

    # Topic progress — driven by the plan's OWN categories (none for a yoga plan)
    topic_progress = []
    if 'topics' in modules:
        for cat in config.get('topic_categories', []):
            entries = TopicEntry.query.filter_by(plan_id=plan.id, category=cat['key']).all()
            solved = sum(e.solved_count for e in entries)
            target = sum(e.target_count for e in entries)
            topic_progress.append({
                'label': cat.get('label', cat['key'].upper()),
                'solved': solved,
                'target': target,
                'pct': min(100, int((solved / target) * 100)) if target else 0,
            })

    # Job / interview KPIs — only when the plan actually has those sections
    total_jobs = JobApplication.query.filter_by(plan_id=plan.id).count() if 'jobs' in modules else 0
    interviews_count = InterviewRecord.query.filter_by(plan_id=plan.id).count() if 'interviews' in modules else 0

    # Weekly data (for charts) — span however many weeks the plan runs
    total_weeks = (plan.duration_days + 6) // 7
    weekly_data = []
    for week_num in range(1, total_weeks + 1):
        start_day = (week_num - 1) * 7 + 1
        end_day = min(week_num * 7, plan.duration_days)
        week_active = 0
        for d in range(start_day, end_day + 1):
            log = logs_by_day.get(d)
            if log and any(log.checkboxes.values()):
                week_active += 1
        weekly_data.append({
            'week': week_num,
            'active_days': week_active,
            'total_days': end_day - start_day + 1,
        })

    # Daily metric trend — one line per numeric metric this plan defines
    last_day = min(days_completed_count, plan.duration_days)
    trend_labels = ['D' + str(d) for d in range(1, last_day + 1)]
    trend_series = []
    for m in config.get('daily_metrics', []):
        if m.get('type', 'number') != 'number':
            continue
        series = []
        for day_num in range(1, last_day + 1):
            log = logs_by_day.get(day_num)
            series.append((log.metrics if log else {}).get(m['key'], 0) or 0)
        trend_series.append({'label': m['label'], 'data': series})

    return {
        'days_elapsed': min(days_completed_count, plan.duration_days),
        'active_days': active_days,
        'overall_pct': overall_pct,
        'current_streak': current_streak,
        'longest_streak': longest_streak,
        'topic_progress': topic_progress,
        'total_jobs': total_jobs,
        'interviews_count': interviews_count,
        'weekly_data': weekly_data,
        'trend_labels': trend_labels,
        'trend_series': trend_series,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PLANS LIST
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/')
@login_required
def plans_list():
    plans = GrowthPlan.query.filter_by(user_id=current_user.id).order_by(GrowthPlan.created_at.desc()).all()
    # Compute quick stats for each plan
    plan_stats = {}
    for plan in plans:
        today = date.today()
        days_elapsed = min((today - plan.start_date).days + 1, plan.duration_days)
        if days_elapsed < 0:
            days_elapsed = 0
        # Count days where at least one checkbox is actually checked.
        # Matches the dashboard's logic — a stored {"dsa": false} must NOT count.
        logs = DailyLog.query.filter_by(plan_id=plan.id).all()
        active_days = sum(1 for log in logs if any(log.checkboxes.values()))
        plan_stats[plan.id] = {
            'days_elapsed': days_elapsed,
            'pct': int((active_days / plan.duration_days) * 100) if plan.duration_days else 0,
        }
    return render_template('tracker/plans_list.html', plans=plans, plan_stats=plan_stats)


# ═══════════════════════════════════════════════════════════════════════════════
# CREATE PLAN
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_plan():
    if request.method == 'POST':
        template = request.form.get('template', 'blank')
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        duration = int(request.form.get('duration', 90))
        start_str = request.form.get('start_date', '')

        if not name:
            flash('Plan name is required.', 'danger')
            return redirect(url_for('tracker.create_plan'))

        try:
            start = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else date.today()
        except ValueError:
            start = date.today()

        plan = GrowthPlan(
            user_id=current_user.id,
            name=name,
            description=description or None,
            template_type=template,
            duration_days=duration,
            start_date=start,
        )

        if template == 'career_90day':
            plan.duration_days = 90
            plan.config = {
                'modules': ['topics', 'jobs', 'interviews', 'weekly', 'skills', 'goals'],
                'daily_checkboxes': CAREER_90DAY_DAILY_CHECKBOXES,
                'daily_metrics': CAREER_90DAY_DAILY_METRICS,
                'weekly_plan': CAREER_90DAY_WEEKLY_PLAN,
                'goals': CAREER_90DAY_GOALS,
                'topic_categories': [
                    {'key': 'dsa', 'label': 'DSA Tracker', 'icon': 'code-2'},
                    {'key': 'sql', 'label': 'SQL Tracker', 'icon': 'database'},
                    {'key': 'datascience', 'label': 'Data Science', 'icon': 'brain'},
                ],
            }
        else:
            # Generic plan (e.g. "60 days yoga"): only universal sections —
            # no DSA/SQL/jobs/interviews/skills, which are career-specific.
            plan.config = {
                'modules': ['weekly', 'goals'],
                'daily_checkboxes': [
                    {'key': 'task1', 'label': 'Task 1 Completed'},
                    {'key': 'task2', 'label': 'Task 2 Completed'},
                ],
                'daily_metrics': [
                    {'key': 'hours', 'label': 'Hours Worked', 'type': 'number'},
                ],
                'weekly_plan': [],
                'goals': {
                    'primary': 'Define your primary goal.',
                    'metrics': [],
                },
                'topic_categories': [],
            }

        db.session.add(plan)
        db.session.flush()  # Get plan.id

        # Seed template data
        if template == 'career_90day':
            # DSA Topics
            for i, (topic, target) in enumerate(CAREER_90DAY_DSA_TOPICS):
                db.session.add(TopicEntry(
                    plan_id=plan.id, category='dsa', topic=topic,
                    target_count=target, solved_count=0, sort_order=i,
                ))
            # SQL Topics
            for i, (topic, target) in enumerate(CAREER_90DAY_SQL_TOPICS):
                db.session.add(TopicEntry(
                    plan_id=plan.id, category='sql', topic=topic,
                    target_count=target, solved_count=0, sort_order=i,
                ))
            # Data Science Topics (target is % completion, stored as solved_count out of 100)
            for i, (topic, target) in enumerate(CAREER_90DAY_DS_TOPICS):
                db.session.add(TopicEntry(
                    plan_id=plan.id, category='datascience', topic=topic,
                    target_count=target, solved_count=0, sort_order=i,
                ))
            # Skills
            for skill_name in CAREER_90DAY_SKILLS:
                db.session.add(SkillRating(
                    plan_id=plan.id, skill_name=skill_name, rating=1,
                ))

        db.session.commit()
        flash(f'Plan "{name}" created successfully!', 'success')
        return redirect(url_for('tracker.dashboard', plan_id=plan.id))

    return render_template('tracker/create_plan.html')


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/<int:plan_id>/')
@login_required
def dashboard(plan_id):
    plan = _get_plan_or_404(plan_id)
    stats = _compute_dashboard_stats(plan)
    return render_template('tracker/dashboard.html', plan=plan, stats=stats)


# ═══════════════════════════════════════════════════════════════════════════════
# DAILY TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/<int:plan_id>/daily', methods=['GET', 'POST'])
@login_required
def daily(plan_id):
    plan = _get_plan_or_404(plan_id)

    if request.method == 'POST':
        day_number = int(request.form.get('day_number', 0))
        if day_number < 1 or day_number > plan.duration_days:
            flash('Invalid day number.', 'danger')
            return redirect(url_for('tracker.daily', plan_id=plan_id))

        if _is_future_day(plan, day_number):
            flash("You can't log a day before it arrives.", 'warning')
            return redirect(url_for('tracker.daily', plan_id=plan_id))

        log = DailyLog.query.filter_by(plan_id=plan.id, day_number=day_number).first()
        if not log:
            log = DailyLog(
                plan_id=plan.id,
                day_number=day_number,
                date=plan.start_date + timedelta(days=day_number - 1),
            )
            db.session.add(log)

        # Update checkboxes
        config = plan.config
        checkboxes = {}
        for cb in config.get('daily_checkboxes', []):
            key = cb['key']
            checkboxes[key] = request.form.get(f'cb_{key}') == 'on'
        log.checkboxes = checkboxes

        # Update metrics
        metrics = {}
        for m in config.get('daily_metrics', []):
            key = m['key']
            val = request.form.get(f'metric_{key}', '0')
            try:
                metrics[key] = float(val) if '.' in str(val) else int(val)
            except (ValueError, TypeError):
                metrics[key] = 0
        log.metrics = metrics

        # Notes
        log.notes = request.form.get('notes', '').strip() or None

        db.session.commit()
        flash(f'Day {day_number} updated!', 'success')
        return redirect(url_for('tracker.daily', plan_id=plan_id))

    # Build all days
    logs = DailyLog.query.filter_by(plan_id=plan.id).order_by(DailyLog.day_number).all()
    logs_map = {log.day_number: log for log in logs}

    today = date.today()
    today_day_number = (today - plan.start_date).days + 1

    days = []
    for d in range(1, plan.duration_days + 1):
        day_date = plan.start_date + timedelta(days=d - 1)
        log = logs_map.get(d)
        days.append({
            'number': d,
            'date': day_date,
            'log': log,
            'checkboxes': log.checkboxes if log else {},
            'metrics': log.metrics if log else {},
            'notes': log.notes if log else '',
            'completion_pct': log.completion_pct if log else 0,
            'is_today': d == today_day_number,
            'is_past': d < today_day_number,
            'is_future': d > today_day_number,
        })

    config = plan.config
    return render_template('tracker/daily.html',
                           plan=plan, days=days, config=config,
                           today_day_number=today_day_number)


@tracker_bp.route('/<int:plan_id>/daily/<int:day_number>/toggle', methods=['POST'])
@login_required
def toggle_daily(plan_id, day_number):
    plan = _get_plan_or_404(plan_id)
    if day_number < 1 or day_number > plan.duration_days:
        return jsonify({'error': 'Invalid day'}), 400

    if _is_future_day(plan, day_number):
        return jsonify({'error': "You can't log a day before it arrives."}), 403

    field = request.form.get('field', '')
    if not field:
        return jsonify({'error': 'No field specified'}), 400

    log = DailyLog.query.filter_by(plan_id=plan.id, day_number=day_number).first()
    if not log:
        log = DailyLog(
            plan_id=plan.id,
            day_number=day_number,
            date=plan.start_date + timedelta(days=day_number - 1),
        )
        db.session.add(log)
        db.session.flush()

    cb = log.checkboxes
    cb[field] = not cb.get(field, False)
    log.checkboxes = cb
    db.session.commit()

    return jsonify({
        'ok': True,
        'field': field,
        'value': cb[field],
        'completion_pct': log.completion_pct,
    })


@tracker_bp.route('/<int:plan_id>/daily/fields', methods=['POST'])
@login_required
def customize_daily(plan_id):
    """Let the user define their own daily checkboxes & metric columns."""
    plan = _get_plan_or_404(plan_id)
    action = request.form.get('action', '')
    config = plan.config
    checkboxes = config.get('daily_checkboxes', []) or []
    metrics = config.get('daily_metrics', []) or []

    def _keys(items):
        return {it['key'] for it in items}

    if action == 'add_checkbox':
        label = request.form.get('label', '').strip()
        if label:
            checkboxes.append({'key': _make_key(label, _keys(checkboxes)), 'label': label})

    elif action == 'rename_checkbox':
        key, label = request.form.get('key', ''), request.form.get('label', '').strip()
        for cb in checkboxes:
            if cb['key'] == key and label:
                cb['label'] = label

    elif action == 'delete_checkbox':
        key = request.form.get('key', '')
        checkboxes = [cb for cb in checkboxes if cb['key'] != key]

    elif action == 'add_metric':
        label = request.form.get('label', '').strip()
        if label:
            metrics.append({'key': _make_key(label, _keys(metrics)), 'label': label, 'type': 'number'})

    elif action == 'rename_metric':
        key, label = request.form.get('key', ''), request.form.get('label', '').strip()
        for m in metrics:
            if m['key'] == key and label:
                m['label'] = label

    elif action == 'delete_metric':
        key = request.form.get('key', '')
        metrics = [m for m in metrics if m['key'] != key]

    config['daily_checkboxes'] = checkboxes
    config['daily_metrics'] = metrics
    plan.config = config
    db.session.commit()
    flash('Daily fields updated!', 'success')
    return redirect(url_for('tracker.daily', plan_id=plan_id))


# ═══════════════════════════════════════════════════════════════════════════════
# TOPIC TRACKER (DSA / SQL / Data Science / Custom)
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/<int:plan_id>/topics/<category>', methods=['GET', 'POST'])
@login_required
def topics(plan_id, category):
    plan = _get_plan_or_404(plan_id)
    redirect_resp = _require_module(plan, 'topics')
    if redirect_resp:
        return redirect_resp

    if request.method == 'POST':
        action = request.form.get('action', 'update')

        if action == 'add':
            topic_name = request.form.get('topic', '').strip()
            target = int(request.form.get('target', 10))
            if topic_name:
                max_order = db.session.query(db.func.max(TopicEntry.sort_order)).filter_by(
                    plan_id=plan.id, category=category
                ).scalar() or 0
                entry = TopicEntry(
                    plan_id=plan.id, category=category, topic=topic_name,
                    target_count=target, solved_count=0, sort_order=max_order + 1,
                )
                db.session.add(entry)
                db.session.commit()
                flash(f'Topic "{topic_name}" added!', 'success')

        elif action == 'update':
            entry_id = int(request.form.get('entry_id', 0))
            entry = TopicEntry.query.get_or_404(entry_id)
            if entry.plan_id != plan.id:
                abort(404)
            solved = request.form.get('solved', '0')
            notes = request.form.get('notes', '').strip()
            try:
                entry.solved_count = int(solved)
            except ValueError:
                pass
            entry.notes = notes or None
            db.session.commit()
            flash('Progress updated!', 'success')

        elif action == 'delete':
            entry_id = int(request.form.get('entry_id', 0))
            entry = TopicEntry.query.get_or_404(entry_id)
            if entry.plan_id != plan.id:
                abort(404)
            db.session.delete(entry)
            db.session.commit()
            flash('Topic removed.', 'info')

        return redirect(url_for('tracker.topics', plan_id=plan_id, category=category))

    entries = TopicEntry.query.filter_by(
        plan_id=plan.id, category=category
    ).order_by(TopicEntry.sort_order).all()

    total_target = sum(e.target_count for e in entries)
    total_solved = sum(e.solved_count for e in entries)
    overall_pct = int((total_solved / total_target) * 100) if total_target else 0

    # Find category label from config
    config = plan.config
    cat_label = category.upper()
    for cat in config.get('topic_categories', []):
        if cat['key'] == category:
            cat_label = cat['label']
            break

    return render_template('tracker/topics.html',
                           plan=plan, category=category, cat_label=cat_label,
                           entries=entries, total_target=total_target,
                           total_solved=total_solved, overall_pct=overall_pct)


# ═══════════════════════════════════════════════════════════════════════════════
# JOB APPLICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/<int:plan_id>/jobs', methods=['GET', 'POST'])
@login_required
def jobs(plan_id):
    plan = _get_plan_or_404(plan_id)
    redirect_resp = _require_module(plan, 'jobs')
    if redirect_resp:
        return redirect_resp

    if request.method == 'POST':
        company = request.form.get('company', '').strip()
        role = request.form.get('role', '').strip()
        platform = request.form.get('platform', '').strip()
        status = request.form.get('status', 'Applied')
        date_str = request.form.get('date', '')
        interview_date_str = request.form.get('interview_date', '')
        result = request.form.get('result', '')
        salary = request.form.get('salary', '').strip()
        notes = request.form.get('notes', '').strip()

        if not company or not role:
            flash('Company and Role are required.', 'danger')
            return redirect(url_for('tracker.jobs', plan_id=plan_id))

        try:
            app_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
        except ValueError:
            app_date = date.today()

        interview_date = None
        if interview_date_str:
            try:
                interview_date = datetime.strptime(interview_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        job = JobApplication(
            plan_id=plan.id,
            date=app_date,
            company=company,
            role=role,
            platform=platform or None,
            status=status,
            interview_date=interview_date,
            result=result or None,
            salary_offered=salary or None,
            notes=notes or None,
        )
        db.session.add(job)
        db.session.commit()
        flash('Job application added!', 'success')
        return redirect(url_for('tracker.jobs', plan_id=plan_id))

    apps = JobApplication.query.filter_by(plan_id=plan.id).order_by(JobApplication.date.desc()).all()

    # Stats
    total = len(apps)
    interviews = sum(1 for a in apps if a.status == 'Interview')
    rejections = sum(1 for a in apps if a.result == 'Rejected')
    offers = sum(1 for a in apps if a.result == 'Selected' or a.status == 'Offered')
    response_rate = int(((interviews + offers + rejections) / total) * 100) if total else 0

    return render_template('tracker/jobs.html',
                           plan=plan, apps=apps,
                           total=total, interviews=interviews,
                           rejections=rejections, offers=offers,
                           response_rate=response_rate)


@tracker_bp.route('/<int:plan_id>/jobs/<int:job_id>/edit', methods=['POST'])
@login_required
def edit_job(plan_id, job_id):
    plan = _get_plan_or_404(plan_id)
    job = JobApplication.query.get_or_404(job_id)
    if job.plan_id != plan.id:
        abort(404)

    job.company = request.form.get('company', job.company).strip()
    job.role = request.form.get('role', job.role).strip()
    job.platform = request.form.get('platform', '').strip() or None
    job.status = request.form.get('status', job.status)
    job.result = request.form.get('result', '').strip() or None
    job.salary_offered = request.form.get('salary', '').strip() or None
    job.notes = request.form.get('notes', '').strip() or None

    interview_date_str = request.form.get('interview_date', '')
    if interview_date_str:
        try:
            job.interview_date = datetime.strptime(interview_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    else:
        job.interview_date = None

    db.session.commit()
    flash('Job application updated!', 'success')
    return redirect(url_for('tracker.jobs', plan_id=plan_id))


@tracker_bp.route('/<int:plan_id>/jobs/<int:job_id>/delete', methods=['POST'])
@login_required
def delete_job(plan_id, job_id):
    plan = _get_plan_or_404(plan_id)
    job = JobApplication.query.get_or_404(job_id)
    if job.plan_id != plan.id:
        abort(404)
    db.session.delete(job)
    db.session.commit()
    flash('Job application deleted.', 'info')
    return redirect(url_for('tracker.jobs', plan_id=plan_id))


# ═══════════════════════════════════════════════════════════════════════════════
# INTERVIEWS
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/<int:plan_id>/interviews', methods=['GET', 'POST'])
@login_required
def interviews(plan_id):
    plan = _get_plan_or_404(plan_id)
    redirect_resp = _require_module(plan, 'interviews')
    if redirect_resp:
        return redirect_resp

    if request.method == 'POST':
        company = request.form.get('company', '').strip()
        date_str = request.form.get('date', '')
        round_name = request.form.get('round_name', '').strip()
        questions = request.form.get('questions', '').strip()
        rating = request.form.get('rating', '')
        weak_areas = request.form.get('weak_areas', '').strip()
        result = request.form.get('result', '')
        followup = request.form.get('followup') == 'on'

        if not company:
            flash('Company name is required.', 'danger')
            return redirect(url_for('tracker.interviews', plan_id=plan_id))

        try:
            int_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
        except ValueError:
            int_date = date.today()

        try:
            rating_val = int(rating) if rating else None
        except ValueError:
            rating_val = None

        record = InterviewRecord(
            plan_id=plan.id,
            company=company,
            date=int_date,
            round_name=round_name or None,
            questions_asked=questions or None,
            performance_rating=rating_val,
            weak_areas=weak_areas or None,
            result=result or None,
            followup_required=followup,
        )
        db.session.add(record)
        db.session.commit()
        flash('Interview recorded!', 'success')
        return redirect(url_for('tracker.interviews', plan_id=plan_id))

    records = InterviewRecord.query.filter_by(plan_id=plan.id).order_by(InterviewRecord.date.desc()).all()
    return render_template('tracker/interviews.html', plan=plan, records=records)


@tracker_bp.route('/<int:plan_id>/interviews/<int:int_id>/delete', methods=['POST'])
@login_required
def delete_interview(plan_id, int_id):
    plan = _get_plan_or_404(plan_id)
    record = InterviewRecord.query.get_or_404(int_id)
    if record.plan_id != plan.id:
        abort(404)
    db.session.delete(record)
    db.session.commit()
    flash('Interview record deleted.', 'info')
    return redirect(url_for('tracker.interviews', plan_id=plan_id))


# ═══════════════════════════════════════════════════════════════════════════════
# WEEKLY PLANNER
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/<int:plan_id>/weekly', methods=['GET', 'POST'])
@login_required
def weekly(plan_id):
    plan = _get_plan_or_404(plan_id)
    redirect_resp = _require_module(plan, 'weekly')
    if redirect_resp:
        return redirect_resp

    if request.method == 'POST':
        action = request.form.get('action', '')
        config = plan.config
        week_list = config.get('weekly_plan', []) or []

        def _topics():
            raw = request.form.get('topics', '')
            return [t.strip() for t in raw.replace('\n', ',').split(',') if t.strip()]

        def _idx():
            try:
                return int(request.form.get('index', -1))
            except (ValueError, TypeError):
                return -1

        if action == 'add_week':
            label = request.form.get('weeks', '').strip()
            if label:
                week_list.append({'weeks': label, 'topics': _topics()})

        elif action == 'update_week':
            i = _idx()
            if 0 <= i < len(week_list):
                week_list[i]['weeks'] = request.form.get('weeks', week_list[i]['weeks']).strip() or week_list[i]['weeks']
                week_list[i]['topics'] = _topics()

        elif action == 'delete_week':
            i = _idx()
            if 0 <= i < len(week_list):
                week_list.pop(i)

        config['weekly_plan'] = week_list
        plan.config = config
        db.session.commit()
        flash('Weekly roadmap updated!', 'success')
        return redirect(url_for('tracker.weekly', plan_id=plan_id))

    config = plan.config
    raw_plan = config.get('weekly_plan', [])

    today = date.today()
    days_elapsed = (today - plan.start_date).days
    current_week = max(1, (days_elapsed // 7) + 1)

    # Enrich each entry with a status, parsing the leading week number safely
    # (custom labels like "Week 1" or "Rest week" must never crash the page).
    weekly_plan = []
    for idx, item in enumerate(raw_plan):
        nums = re.findall(r'\d+', str(item.get('weeks', '')))
        status = 'upcoming'
        if nums:
            wstart = int(nums[0])
            wend = int(nums[-1])
            if current_week > wend:
                status = 'completed'
            elif wstart <= current_week <= wend:
                status = 'current'
        weekly_plan.append({
            'index': idx,
            'weeks': item.get('weeks', ''),
            'topics': item.get('topics', []),
            'status': status,
        })

    return render_template('tracker/weekly.html',
                           plan=plan, weekly_plan=weekly_plan,
                           current_week=current_week)


# ═══════════════════════════════════════════════════════════════════════════════
# SKILL MATRIX
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/<int:plan_id>/skills', methods=['GET', 'POST'])
@login_required
def skills(plan_id):
    plan = _get_plan_or_404(plan_id)
    redirect_resp = _require_module(plan, 'skills')
    if redirect_resp:
        return redirect_resp

    if request.method == 'POST':
        ratings = SkillRating.query.filter_by(plan_id=plan.id).all()
        for sr in ratings:
            val = request.form.get(f'skill_{sr.id}', '')
            try:
                sr.rating = max(1, min(10, int(val)))
            except (ValueError, TypeError):
                pass
        db.session.commit()
        flash('Skills updated!', 'success')
        return redirect(url_for('tracker.skills', plan_id=plan_id))

    ratings = SkillRating.query.filter_by(plan_id=plan.id).order_by(SkillRating.id).all()
    return render_template('tracker/skills.html', plan=plan, ratings=ratings)


# ═══════════════════════════════════════════════════════════════════════════════
# GOALS
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/<int:plan_id>/goals', methods=['GET', 'POST'])
@login_required
def goals(plan_id):
    plan = _get_plan_or_404(plan_id)
    redirect_resp = _require_module(plan, 'goals')
    if redirect_resp:
        return redirect_resp

    if request.method == 'POST':
        action = request.form.get('action', '')
        config = plan.config
        goals_cfg = config.get('goals', {}) or {}
        metric_list = goals_cfg.get('metrics', []) or []

        def _int(name, default=0):
            try:
                return int(request.form.get(name, default))
            except (ValueError, TypeError):
                return default

        if action == 'update_primary':
            goals_cfg['primary'] = request.form.get('primary', '').strip() or 'Define your primary goal.'

        elif action == 'add_metric':
            name = request.form.get('name', '').strip()
            if name:
                metric_list.append({
                    'name': name,
                    'target': max(1, _int('target', 1)),
                    'current': max(0, _int('current', 0)),
                    'source': 'manual',
                })

        elif action == 'update_metric':
            idx = _int('index', -1)
            if 0 <= idx < len(metric_list) and metric_list[idx].get('source', 'manual') == 'manual':
                metric_list[idx]['name'] = request.form.get('name', metric_list[idx]['name']).strip() or metric_list[idx]['name']
                metric_list[idx]['target'] = max(1, _int('target', metric_list[idx].get('target', 1)))
                metric_list[idx]['current'] = max(0, _int('current', metric_list[idx].get('current', 0)))

        elif action == 'delete_metric':
            idx = _int('index', -1)
            if 0 <= idx < len(metric_list) and metric_list[idx].get('source', 'manual') == 'manual':
                metric_list.pop(idx)

        goals_cfg['metrics'] = metric_list
        config['goals'] = goals_cfg
        plan.config = config          # reassign — the JSON property only persists on set
        db.session.commit()
        flash('Goals updated!', 'success')
        return redirect(url_for('tracker.goals', plan_id=plan_id))

    config = plan.config
    goals_config = config.get('goals', {})

    # Compute live progress for each metric
    metrics = []
    for idx, m in enumerate(goals_config.get('metrics', [])):
        current = 0
        source = m.get('source', '')

        if source == 'dsa':
            current = db.session.query(db.func.sum(TopicEntry.solved_count)).filter_by(
                plan_id=plan.id, category='dsa'
            ).scalar() or 0
        elif source == 'sql':
            current = db.session.query(db.func.sum(TopicEntry.solved_count)).filter_by(
                plan_id=plan.id, category='sql'
            ).scalar() or 0
        elif source == 'jobs':
            current = JobApplication.query.filter_by(plan_id=plan.id).count()
        elif source == 'interviews':
            current = InterviewRecord.query.filter_by(plan_id=plan.id).count()
        elif source == 'ds_project':
            # Count DS topics with 100% completion
            current = TopicEntry.query.filter_by(
                plan_id=plan.id, category='datascience'
            ).filter(TopicEntry.solved_count >= 100).count()
            current = min(current, m.get('target', 1))
        elif source == 'skill_nextjs':
            sr = SkillRating.query.filter_by(plan_id=plan.id, skill_name='Next.js').first()
            current = (sr.rating * 10) if sr else 0
        else:
            current = m.get('current', 0)  # Manual goals — user-entered progress

        target = m.get('target', 1)
        pct = min(100, int((current / target) * 100)) if target else 0
        metrics.append({
            'index': idx,
            'name': m['name'],
            'target': target,
            'current': current,
            'pct': pct,
            'editable': source in ('', 'manual'),
        })

    return render_template('tracker/goals.html',
                           plan=plan, goals_config=goals_config, metrics=metrics)


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE PLAN
# ═══════════════════════════════════════════════════════════════════════════════

@tracker_bp.route('/<int:plan_id>/delete', methods=['POST'])
@login_required
def delete_plan(plan_id):
    plan = _get_plan_or_404(plan_id)
    db.session.delete(plan)
    db.session.commit()
    flash(f'Plan "{plan.name}" deleted.', 'info')
    return redirect(url_for('tracker.plans_list'))
