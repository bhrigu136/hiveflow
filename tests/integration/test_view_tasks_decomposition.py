"""Behaviour-preservation coverage for the view_tasks decomposition (C7).

view_tasks had no tests. Its filtered-query and summary-stats logic was
extracted verbatim into tasks._query_personal_tasks and tasks._task_stats.
These pin both helpers directly and confirm the route still renders.
"""
from datetime import date

import pytest

from app.extensions import db
from app.models import Task
from app.routes.tasks import _query_personal_tasks, _task_stats
from tests.factories import login, make_org, make_project, make_user


class _T:
    def __init__(self, status):
        self.status = status


class TestTaskStats:
    def test_counts_and_percentage(self):
        tasks = [_T('Completed'), _T('Completed'), _T('Pending'), _T('Working')]
        assert _task_stats(tasks) == {
            'total_count': 4, 'pending_count': 1, 'working_count': 1,
            'completed_count': 2, 'completion_pct': 50,
        }

    def test_empty_is_zero_pct(self):
        assert _task_stats([])['completion_pct'] == 0

    def test_percentage_truncates_like_int(self):
        tasks = [_T('Completed'), _T('Pending'), _T('Pending')]  # 1/3
        assert _task_stats(tasks)['completion_pct'] == 33


@pytest.mark.integration
class TestQueryPersonalTasks:
    def _seed(self, app):
        with app.app_context():
            u = make_user("vt_user")
            other = make_user("vt_other")
            org = make_org("VT Co", u)
            proj = make_project(org, u)
            db.session.add_all([
                Task(title="P-high", user_id=u.id, priority="High", status="Pending"),
                Task(title="W-low", user_id=u.id, priority="Low", status="Working"),
                Task(title="proj-task", user_id=u.id, project_id=proj.id, status="Pending"),
                Task(title="others", user_id=other.id, priority="High", status="Pending"),
            ])
            db.session.commit()
            return u.id

    def test_personal_only_excludes_project_and_other_users(self, app):
        uid = self._seed(app)
        with app.app_context():
            res = _query_personal_tasks(uid, 'all', 'all', '', None, date.today())
            assert {t.title for t in res} == {"P-high", "W-low"}

    def test_status_filter(self, app):
        uid = self._seed(app)
        with app.app_context():
            res = _query_personal_tasks(uid, 'Working', 'all', '', None, date.today())
            assert {t.title for t in res} == {"W-low"}

    def test_priority_and_search_filters(self, app):
        uid = self._seed(app)
        with app.app_context():
            assert {t.title for t in _query_personal_tasks(uid, 'all', 'High', '', None, date.today())} == {"P-high"}
            assert {t.title for t in _query_personal_tasks(uid, 'all', 'all', 'high', None, date.today())} == {"P-high"}


@pytest.mark.integration
class TestViewTasksRoute:
    def test_route_renders_personal_task(self, app, client):
        with app.app_context():
            u = make_user("vt_route")
            db.session.add(Task(title="RenderMe", user_id=u.id, priority="High", status="Pending"))
            db.session.commit()
        login(client, "vt_route")
        r = client.get("/?date=all")
        assert r.status_code == 200
        assert "RenderMe" in r.get_data(as_text=True)
