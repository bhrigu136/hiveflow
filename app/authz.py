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
