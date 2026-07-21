"""Authorization helpers.

Organization-membership checks were duplicated across route modules — the same
``OrgMember.query.filter_by(org_id=..., user_id=current_user.id)`` appeared many
times, and ``check_project_access`` was defined identically in more than one
blueprint. Both confirmed IDORs (SEC-003, SEC-004) were omissions of exactly
this kind of check, which is easier to get wrong when it lives in a dozen
places.

This module is the single home for those checks. Behaviour is intentionally
identical to the previous inline versions — it is a de-duplication, not a
policy change. The eventual decorator layer (deferred until the role model
changes) will build on these same helpers.
"""
from flask_login import current_user

from app.models import OrgMember


def is_org_member(org_id) -> bool:
    """True if the current user belongs to the organization."""
    if not org_id:
        return False
    return OrgMember.query.filter_by(
        org_id=org_id, user_id=current_user.id
    ).first() is not None


def is_org_admin(org_id) -> bool:
    """True if the current user is an Admin of the organization."""
    if not org_id:
        return False
    member = OrgMember.query.filter_by(
        org_id=org_id, user_id=current_user.id
    ).first()
    return member is not None and member.role == 'Admin'


def check_project_access(project) -> bool:
    """True if the current user is in the project's organization.

    Takes a Project object. Mirrors the helper previously duplicated in the
    discussions and meetings blueprints.
    """
    return is_org_member(project.org_id)


# ─────────────────────────────────────────────────────────────────────────────
# Authorization decorators (Phase C)
#
# The routes gate on org membership in many different ways — the org id is
# resolved from a <slug>, an <int:project_id>, or a loaded object
# (meeting.org_id, discussion.project.org_id, doc.org_id) — and they DENY in
# several deliberately different ways: flash+redirect (to various places),
# abort(404) (the docs existence-disclosure control), abort(403), or a JSON 403
# for AJAX endpoints.
#
# A single decorator cannot flatten that without breaking behaviour, so the
# decorators are parameterized by two callables:
#   * a RESOLVER  (view kwargs) -> _Access(org_id, obj)   — how to find the org
#   * a DENY handler (_Access)  -> Response               — what to do on refusal
#
# Resolvers stash the object they load on flask.g (`g.authz_obj`) so a migrated
# view can read it instead of querying again. Factories for the common resolvers
# and deny styles are provided below; each existing gate maps onto one pair.
# ─────────────────────────────────────────────────────────────────────────────
import functools

from flask import abort, flash, g, jsonify, redirect, url_for


class _Access:
    """The resolved authorization context for one request: the org id to check,
    and the object it was resolved from (also stashed on ``g.authz_obj``)."""
    __slots__ = ('org_id', 'obj')

    def __init__(self, org_id, obj=None):
        self.org_id = org_id
        self.obj = obj


# ── resolver factories: (view kwargs) -> _Access ─────────────────────────────

def by_slug(param='slug'):
    """Resolve the org from an Organization slug route param (404 if unknown)."""
    def resolve(kwargs):
        from app.models import Organization
        org = Organization.query.filter_by(slug=kwargs[param]).first_or_404()
        g.authz_obj = org
        return _Access(org.id, org)
    return resolve


def by_org_id(param='org_id'):
    """Resolve the org from an org id already present in the route kwargs."""
    def resolve(kwargs):
        return _Access(kwargs[param], None)
    return resolve


def by_project(param='project_id'):
    """Resolve the org that owns a Project (404 if the project is unknown)."""
    def resolve(kwargs):
        from app.models import Project
        project = Project.query.get_or_404(kwargs[param])
        g.authz_obj = project
        return _Access(project.org_id, project)
    return resolve


def by_meeting(param='meeting_id'):
    """Resolve the org that owns a Meeting (404 if unknown)."""
    def resolve(kwargs):
        from app.models import Meeting
        meeting = Meeting.query.get_or_404(kwargs[param])
        g.authz_obj = meeting
        return _Access(meeting.org_id, meeting)
    return resolve


def by_discussion(param='discussion_id'):
    """Resolve the org that owns a Discussion via its project (404 if unknown)."""
    def resolve(kwargs):
        from app.models import Discussion
        discussion = Discussion.query.get_or_404(kwargs[param])
        g.authz_obj = discussion
        return _Access(discussion.project.org_id, discussion)
    return resolve


def by_document(param='doc_id'):
    """Resolve the org that owns a Document (404 if unknown)."""
    def resolve(kwargs):
        from app.models import Document
        doc = Document.query.get_or_404(kwargs[param])
        g.authz_obj = doc
        return _Access(doc.org_id, doc)
    return resolve


# ── deny handlers: (_Access) -> Response ─────────────────────────────────────

def redirect_flash(endpoint, message, category='danger', values=None):
    """Deny by flashing ``message`` and redirecting to ``endpoint``.

    ``values`` may be a dict of url_for kwargs, or a callable ``(_Access) ->
    dict`` for redirect targets that depend on the resolved object (e.g.
    ``orgs.dashboard`` needs ``slug=org.slug``).
    """
    def deny(access):
        flash(message, category)
        v = values(access) if callable(values) else (values or {})
        return redirect(url_for(endpoint, **v))
    return deny


def json_403(message='access denied'):
    """Deny with an AJAX/API-style ``{'error': ...}, 403`` response."""
    def deny(access):
        return jsonify({'error': message}), 403
    return deny


def abort_status(code):
    """Deny by aborting with an HTTP status (e.g. 404 for docs disclosure)."""
    def deny(access):
        abort(code)
    return deny


# ── the decorators ───────────────────────────────────────────────────────────

def require_org_member(resolver, on_deny):
    """Allow the view only if the current user is a member of the resolved org.

    ``resolver`` maps the view's kwargs to an :class:`_Access`; ``on_deny`` turns
    a refusal into the exact response that route used before. Apply it under
    ``@login_required`` (it assumes an authenticated ``current_user``).
    """
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            access = resolver(kwargs)
            if not is_org_member(access.org_id):
                return on_deny(access)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def require_org_admin(resolver, on_deny):
    """Allow the view only if the current user is an Admin of the resolved org.

    Same contract as :func:`require_org_member`, using :func:`is_org_admin`.
    """
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            access = resolver(kwargs)
            if not is_org_admin(access.org_id):
                return on_deny(access)
            return view(*args, **kwargs)
        return wrapped
    return decorator
