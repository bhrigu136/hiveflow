"""Analytics aggregations for org + project dashboards.

Replaces the per-member Python loops in the old analytics views with SQL
GROUP BY queries, and buckets time series in Python (portable across Postgres
and SQLite). Results are cached briefly so a dashboard refresh doesn't re-run
the aggregations on every hit.

All datetime math uses naive UTC to match how the app stores timestamps
(`datetime.now(timezone.utc)` written into naive DateTime columns).
"""
from collections import OrderedDict
from datetime import datetime, timezone, timedelta

import cachetools
from sqlalchemy import func, case

from app.extensions import db
from app.models import Task, Meeting, Project, User

# Short TTL: dashboards feel live without re-aggregating on every request.
_cache = cachetools.TTLCache(maxsize=256, ttl=90)

_VELOCITY_WEEKS = 8


def _now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def org_analytics(org_id, days=30):
    key = ('org', org_id, days)
    if key in _cache:
        return _cache[key]
    project_ids = [p.id for p in Project.query.filter_by(org_id=org_id).all()]
    data = _compute(project_ids, days, org_id=org_id)
    _cache[key] = data
    return data


def project_analytics(project_id, days=30):
    key = ('project', project_id, days)
    if key in _cache:
        return _cache[key]
    data = _compute([project_id], days, org_id=None)
    _cache[key] = data
    return data


def _compute(project_ids, days, org_id=None):
    now = _now_naive()
    today = now.date()
    result = {
        'totals': {'total': 0, 'completed': 0, 'working': 0, 'pending': 0, 'overdue': 0,
                   'completion_rate': 0},
        'status': {'Completed': 0, 'Working': 0, 'Pending': 0},
        'velocity': {'labels': [], 'data': []},
        'members': [],
        'meetings': {'count': 0, 'total_hours': 0},
        'has_data': False,
    }
    if not project_ids:
        return result

    in_scope = Task.project_id.in_(project_ids)

    # ── Status distribution + totals (one GROUP BY) ──
    for status, cnt in (db.session.query(Task.status, func.count(Task.id))
                        .filter(in_scope).group_by(Task.status).all()):
        cnt = int(cnt)
        result['totals']['total'] += cnt
        if status in result['status']:
            result['status'][status] = cnt
        key = (status or '').lower()
        if key in result['totals']:
            result['totals'][key] = cnt

    total = result['totals']['total']
    result['totals']['completion_rate'] = (
        int(result['totals']['completed'] / total * 100) if total else 0)

    # ── Overdue (deadline passed, not completed) ──
    result['totals']['overdue'] = int(
        db.session.query(func.count(Task.id))
        .filter(in_scope, Task.deadline.isnot(None), Task.deadline < today,
                Task.status != 'Completed').scalar() or 0)

    # ── Velocity: completed per week over the last N weeks (Python-bucketed) ──
    week_start = today - timedelta(days=today.weekday())  # Monday of this week
    buckets = OrderedDict()
    for i in range(_VELOCITY_WEEKS - 1, -1, -1):
        buckets[week_start - timedelta(weeks=i)] = 0
    earliest = week_start - timedelta(weeks=_VELOCITY_WEEKS - 1)
    completed_dates = (db.session.query(Task.completed_at)
                       .filter(in_scope, Task.status == 'Completed',
                               Task.completed_at.isnot(None),
                               Task.completed_at >= datetime.combine(earliest, datetime.min.time()))
                       .all())
    for (cat,) in completed_dates:
        if cat is None:
            continue
        d = cat.date() if hasattr(cat, 'date') else cat
        wk = d - timedelta(days=d.weekday())
        if wk in buckets:
            buckets[wk] += 1
    result['velocity']['labels'] = [d.strftime('%b %d') for d in buckets]
    result['velocity']['data'] = list(buckets.values())

    # ── Per-member throughput (GROUP BY assigned_to) ──
    member_rows = (db.session.query(
                       Task.assigned_to,
                       func.count(Task.id),
                       func.sum(case((Task.status == 'Completed', 1), else_=0)))
                   .filter(in_scope, Task.assigned_to.isnot(None))
                   .group_by(Task.assigned_to).all())
    names = {}
    uids = [r[0] for r in member_rows]
    if uids:
        names = {u.id: (u.name or u.username)
                 for u in User.query.filter(User.id.in_(uids)).all()}
    members = [{'name': names.get(uid, 'Unknown'),
               'total': int(tot), 'completed': int(done or 0)}
              for uid, tot, done in member_rows]
    members.sort(key=lambda m: m['completed'], reverse=True)
    result['members'] = members

    # ── Meeting hours over the window (org-scoped only) ──
    if org_id is not None:
        row = (db.session.query(func.count(Meeting.id),
                                func.coalesce(func.sum(Meeting.duration_minutes), 0))
               .filter(Meeting.org_id == org_id,
                       Meeting.scheduled_for >= (now - timedelta(days=days)))
               .first())
        if row:
            result['meetings'] = {'count': int(row[0] or 0),
                                  'total_hours': round(float(row[1] or 0) / 60.0, 1)}

    result['has_data'] = total > 0
    return result
