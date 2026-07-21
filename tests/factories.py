"""Test data builders.

The canonical graph has TWO organizations so every cross-tenant test has a
real "other tenant" to assert against — without it, the IDOR regressions
cannot be written.

All builders run inside the caller's app context and flush (not commit) so ids
are available; the fixture owning the context handles teardown.
"""
from app.extensions import db
from app.models import (Discussion, Organization, OrgMember, Project, Task,
                        User)


def make_user(username, *, verified=True):
    u = User(username=username, email=f"{username}@example.com",
             email_verified=verified)
    u.set_password("Passw0rd")
    db.session.add(u)
    db.session.flush()
    return u


def make_org(name, owner, *, invite=None):
    slug = name.lower().replace(" ", "-")
    org = Organization(name=name, slug=slug,
                       invite_code=invite or slug.upper()[:8],
                       created_by=owner.id)
    db.session.add(org)
    db.session.flush()
    db.session.add(OrgMember(org_id=org.id, user_id=owner.id, role="Admin"))
    db.session.flush()
    return org


def add_member(org, user, role="Member"):
    m = OrgMember(org_id=org.id, user_id=user.id, role=role)
    db.session.add(m)
    db.session.flush()
    return m


def make_project(org, creator, name="Project"):
    p = Project(name=name, org_id=org.id, created_by=creator.id)
    db.session.add(p)
    db.session.flush()
    return p


def make_task(owner, *, project=None, title="Task", assigned_to=None):
    t = Task(title=title, user_id=owner.id,
             project_id=project.id if project else None,
             assigned_to=assigned_to)
    db.session.add(t)
    db.session.flush()
    return t


def make_discussion(project, creator, title="Discussion"):
    d = Discussion(title=title, content="body", project_id=project.id,
                   created_by=creator.id)
    db.session.add(d)
    db.session.flush()
    return d


def two_org_world():
    """Build the canonical two-tenant fixture and return a dict of ids.

    Org A: admin_a (Admin), member_a (Member) — one project, one project task,
           one personal task, one discussion.
    Org B: outsider (Admin) — belongs to no part of Org A.
    nobody: registered, member of no organization.
    """
    admin_a = make_user("admin_a")
    member_a = make_user("member_a")
    outsider = make_user("outsider")
    nobody = make_user("nobody")

    org_a = make_org("Org A", admin_a, invite="ORGA")
    add_member(org_a, member_a, role="Member")
    org_b = make_org("Org B", outsider, invite="ORGB")

    proj_a = make_project(org_a, admin_a, name="Project A")
    task_a = make_task(admin_a, project=proj_a, title="A project task")
    personal_a = make_task(admin_a, title="A personal task")
    disc_a = make_discussion(proj_a, admin_a)

    db.session.commit()
    return {
        "admin_a": admin_a.id, "member_a": member_a.id,
        "outsider": outsider.id, "nobody": nobody.id,
        "org_a": org_a.id, "org_b": org_b.id,
        "project_a": proj_a.id, "task_a": task_a.id,
        "personal_a": personal_a.id, "discussion_a": disc_a.id,
    }


def login(client, username):
    """Log a client in and confirm its identity, guarding against the session
    leak documented in conftest.py. Returns the client."""
    client.post("/auth/login",
                data={"email": f"{username}@example.com", "password": "Passw0rd"})
    body = client.get("/auth/profile").get_data(as_text=True)
    assert username in body, (
        f"session-isolation failure: client logged in as {username!r} but "
        f"/auth/profile does not show them"
    )
    return client
