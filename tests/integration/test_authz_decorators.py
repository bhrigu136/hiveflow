"""Unit coverage for the Phase C authorization decorators (C1).

These mount throwaway routes on the test app — the real routes are untouched by
C1 — and assert that require_org_member / require_org_admin enforce access AND
reproduce every deny style the real routes use: flash+redirect (302), JSON 403,
and abort(404). Also checks that resolvers 404 on unknown ids before the
membership check, and that the by_project resolver resolves org via the project.
"""
import pytest

from app import authz
from tests.factories import login, two_org_world


def _ok(**kwargs):
    return "OK", 200


def _mount(app):
    """Mount one route per (decorator, resolver, deny-style) combination."""
    app.add_url_rule(
        '/t/member-redirect/<slug>', 'tmr',
        authz.require_org_member(
            authz.by_slug(), authz.redirect_flash('orgs.list_orgs', 'nope'))(_ok))
    app.add_url_rule(
        '/t/member-json/<slug>', 'tmj',
        authz.require_org_member(
            authz.by_slug(), authz.json_403('access denied'))(_ok))
    app.add_url_rule(
        '/t/member-404/<slug>', 'tm4',
        authz.require_org_member(
            authz.by_slug(), authz.abort_status(404))(_ok))
    app.add_url_rule(
        '/t/admin-redirect/<slug>', 'tar',
        authz.require_org_admin(
            authz.by_slug(),
            authz.redirect_flash('orgs.dashboard', 'nope',
                                 values=lambda a: {'slug': a.obj.slug}))(_ok))
    app.add_url_rule(
        '/t/project-json/<int:project_id>', 'tpj',
        authz.require_org_member(
            authz.by_project(), authz.json_403())(_ok))


@pytest.fixture
def world(app):
    with app.app_context():
        return two_org_world()


@pytest.fixture
def mounted(app):
    _mount(app)
    return app


@pytest.mark.integration
class TestRequireOrgMember:
    def test_member_allowed(self, mounted, make_client, world):
        c = login(make_client(), "member_a")
        r = c.get("/t/member-redirect/org-a")
        assert r.status_code == 200 and r.get_data(as_text=True) == "OK"

    def test_outsider_denied_via_redirect(self, mounted, make_client, world):
        c = login(make_client(), "outsider")
        r = c.get("/t/member-redirect/org-a", follow_redirects=False)
        assert r.status_code == 302

    def test_outsider_denied_via_json_403(self, mounted, make_client, world):
        c = login(make_client(), "outsider")
        r = c.get("/t/member-json/org-a")
        assert r.status_code == 403 and r.get_json()["error"] == "access denied"

    def test_outsider_denied_via_abort_404(self, mounted, make_client, world):
        c = login(make_client(), "outsider")
        assert c.get("/t/member-404/org-a").status_code == 404

    def test_unknown_slug_is_404_before_membership_check(self, mounted, make_client, world):
        c = login(make_client(), "member_a")
        assert c.get("/t/member-redirect/no-such-org").status_code == 404

    def test_by_project_resolver_allows_member_denies_outsider(self, mounted, make_client, world):
        assert login(make_client(), "member_a").get(
            f"/t/project-json/{world['project_a']}").status_code == 200
        assert login(make_client(), "outsider").get(
            f"/t/project-json/{world['project_a']}").status_code == 403


@pytest.mark.integration
class TestRequireOrgAdmin:
    def test_admin_allowed(self, mounted, make_client, world):
        c = login(make_client(), "admin_a")
        assert c.get("/t/admin-redirect/org-a").status_code == 200

    def test_plain_member_denied(self, mounted, make_client, world):
        c = login(make_client(), "member_a")  # Member, not Admin
        r = c.get("/t/admin-redirect/org-a", follow_redirects=False)
        assert r.status_code == 302

    def test_outsider_denied(self, mounted, make_client, world):
        c = login(make_client(), "outsider")
        r = c.get("/t/admin-redirect/org-a", follow_redirects=False)
        assert r.status_code == 302

    def test_admin_redirect_target_uses_resolved_object(self, mounted, make_client, world):
        # values=lambda a: {'slug': a.obj.slug} must build /orgs/org-a/... target
        c = login(make_client(), "member_a")
        r = c.get("/t/admin-redirect/org-a", follow_redirects=False)
        assert r.status_code == 302 and "/orgs/org-a" in r.headers["Location"]
