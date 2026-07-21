"""Behaviour-preservation coverage for the analytics per-member rollup (B3).

`orgs.analytics` and `projects.analytics` each contained a byte-identical
per-member loop building `members_data`. B3 extracted it to
`app.services.analytics.member_task_breakdown`. These tests pin that the helper
returns exactly what the old inline loop returned, and that both analytics
routes still render for an Admin.
"""
from datetime import datetime

import pytest

from app.services.analytics import member_task_breakdown
from tests.factories import login, two_org_world


# ── lightweight stand-ins: the helper only reads these attributes ─────────────

class _Member:
    def __init__(self, user_id):
        self.user_id = user_id


class _Task:
    def __init__(self, assigned_to, status, created_at):
        self.assigned_to = assigned_to
        self.status = status
        self.created_at = created_at


def _old_inline_loop(members, tasks):
    """Verbatim copy of the loop that lived in the two analytics views, kept
    here as the reference implementation the extraction must match exactly."""
    members_data = []
    for member in members:
        member_tasks = [t for t in tasks if t.assigned_to == member.user_id]
        total_assigned = len(member_tasks)
        completed = sum(1 for t in member_tasks if t.status == 'Completed')
        pending = sum(1 for t in member_tasks if t.status == 'Pending')
        working = sum(1 for t in member_tasks if t.status == 'Working')
        completion_rate = int((completed / total_assigned) * 100) if total_assigned > 0 else 0
        recent_tasks = sorted(
            [t for t in member_tasks if t.status == 'Completed'],
            key=lambda t: t.created_at, reverse=True,
        )[:5]
        members_data.append({
            'member': member, 'total': total_assigned, 'completed': completed,
            'pending': pending, 'working': working,
            'completion_rate': completion_rate, 'recent_tasks': recent_tasks,
        })
    members_data.sort(key=lambda x: x['completed'], reverse=True)
    return members_data


def _sample():
    m1, m2 = _Member(1), _Member(2)
    tasks = [
        _Task(1, 'Completed', datetime(2026, 1, 1)),
        _Task(1, 'Completed', datetime(2026, 1, 4)),
        _Task(1, 'Pending', datetime(2026, 1, 2)),
        _Task(1, 'Working', datetime(2026, 1, 3)),
        _Task(2, 'Completed', datetime(2026, 1, 5)),
        _Task(2, 'Completed', datetime(2026, 1, 6)),
        _Task(2, 'Completed', datetime(2026, 1, 7)),
        _Task(99, 'Completed', datetime(2026, 1, 8)),  # unassigned to either member
    ]
    return [m1, m2], tasks


class TestMemberTaskBreakdown:
    def test_matches_old_inline_loop_exactly(self):
        members, tasks = _sample()
        assert member_task_breakdown(members, tasks) == _old_inline_loop(members, tasks)

    def test_completion_rate_truncates_like_int(self):
        m = _Member(1)
        tasks = [
            _Task(1, 'Completed', datetime(2026, 1, 1)),
            _Task(1, 'Completed', datetime(2026, 1, 2)),
            _Task(1, 'Pending', datetime(2026, 1, 3)),
        ]
        row = member_task_breakdown([m], tasks)[0]
        assert row['total'] == 3 and row['completed'] == 2
        assert row['completion_rate'] == 66  # int(66.66...), not rounded to 67

    def test_recent_tasks_capped_at_5_newest_first(self):
        m = _Member(1)
        tasks = [_Task(1, 'Completed', datetime(2026, 1, d)) for d in range(1, 8)]  # 7
        row = member_task_breakdown([m], tasks)[0]
        dates = [t.created_at for t in row['recent_tasks']]
        assert len(dates) == 5
        assert dates == sorted(dates, reverse=True)
        assert dates[0] == datetime(2026, 1, 7)

    def test_sorted_by_completed_descending(self):
        m1, m2 = _Member(1), _Member(2)
        tasks = [
            _Task(2, 'Completed', datetime(2026, 1, 1)),
            _Task(2, 'Completed', datetime(2026, 1, 2)),
            _Task(1, 'Completed', datetime(2026, 1, 1)),
        ]
        rows = member_task_breakdown([m1, m2], tasks)
        assert rows[0]['member'] is m2 and rows[1]['member'] is m1

    def test_empty_inputs(self):
        assert member_task_breakdown([], []) == []
        row = member_task_breakdown([_Member(1)], [])[0]
        assert row['total'] == 0 and row['completion_rate'] == 0 and row['recent_tasks'] == []


@pytest.mark.integration
class TestAnalyticsRoutesStillRender:
    """The two routes that used the extracted loop must still render for an Admin."""

    def test_org_analytics_renders(self, app, make_client):
        with app.app_context():
            two_org_world()
        c = login(make_client(), "admin_a")
        r = c.get("/orgs/org-a/analytics")
        assert r.status_code == 200

    def test_project_analytics_renders(self, app, make_client):
        with app.app_context():
            world = two_org_world()
        c = login(make_client(), "admin_a")
        r = c.get(f"/projects/{world['project_a']}/analytics")
        assert r.status_code == 200
