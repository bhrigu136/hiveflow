"""Team Docs / Wiki — org-scoped nested rich documents.

Markdown is the source of truth; it is sanitized to HTML on every save (see
`app/docs_render.py`) and the viewer renders that cached HTML. Access is gated by
org membership, mirroring the inline/local-helper style used elsewhere in the app
(no global decorator). Non-members get 404 (not 403) so doc existence isn't
leaked across tenants.
"""
from datetime import datetime, timezone, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify, abort)
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from app.extensions import db
from app.models import Organization, OrgMember, Document, DocumentRevision
from app.docs_render import render_markdown, to_plain_text, MAX_MARKDOWN_BYTES
from app.authz import is_org_member, get_membership

docs_bp = Blueprint('docs', __name__)

_REVISION_KEEP = 50


# ── Access / helpers ───────────────────────────────────────────────────────

def _is_postgres():
    return db.engine.dialect.name == 'postgresql'


def _require_org(slug, min_role=None):
    org = Organization.query.filter_by(slug=slug).first_or_404()
    membership = get_membership(org.id)
    if membership is None:
        abort(404)  # 404, not 403 — don't reveal the workspace exists
    if min_role == 'Admin' and membership.role != 'Admin':
        abort(403)
    return org, membership


def _get_doc_or_404(org, doc_id):
    return (Document.query
            .filter(Document.id == doc_id, Document.org_id == org.id,
                    Document.deleted_at.is_(None))
            .first_or_404())


def _require_doc_access(doc_id):
    """For id-only routes (autosave/reorder): load doc + verify org membership."""
    doc = Document.query.filter(Document.id == doc_id,
                                Document.deleted_at.is_(None)).first_or_404()
    membership = get_membership(doc.org_id)
    if membership is None:
        abort(404)
    return doc, doc.organization, membership


def _build_tree(org_id):
    """One ordered query → {parent_id: [children...]} for recursive rendering."""
    docs = (Document.query
            .filter(Document.org_id == org_id,
                    Document.deleted_at.is_(None),
                    Document.is_archived.is_(False))
            .order_by(Document.sort_order, Document.id).all())
    nodes_by_parent = {}
    for d in docs:
        nodes_by_parent.setdefault(d.parent_id, []).append(d)
    return nodes_by_parent


def _ancestors(doc):
    chain, seen, cur = [], set(), doc.parent
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        chain.append(cur)
        cur = cur.parent
    return list(reversed(chain))


def _would_cycle(doc, new_parent_id):
    """True if re-parenting `doc` under new_parent_id would create a cycle
    (new parent is the doc itself or one of its descendants)."""
    if new_parent_id is None:
        return False
    if new_parent_id == doc.id:
        return True
    cur, seen = Document.query.get(new_parent_id), set()
    while cur is not None and cur.id not in seen:
        if cur.id == doc.id:
            return True
        seen.add(cur.id)
        cur = cur.parent
    return False


def _prune_revisions(doc_id):
    count = DocumentRevision.query.filter_by(document_id=doc_id).count()
    if count > _REVISION_KEEP:
        old = (DocumentRevision.query.filter_by(document_id=doc_id)
               .order_by(DocumentRevision.created_at.asc())
               .limit(count - _REVISION_KEEP).all())
        for r in old:
            db.session.delete(r)


# ── Pages ──────────────────────────────────────────────────────────────────

@docs_bp.route('/docs')
@login_required
def hub():
    """Top-level 'Docs' entry: the user's workspaces with doc counts."""
    org_ids = [m.org_id for m in OrgMember.query.filter_by(user_id=current_user.id).all()]
    orgs, counts = [], {}
    if org_ids:
        orgs = Organization.query.filter(Organization.id.in_(org_ids)).order_by(Organization.name).all()
        for o in orgs:
            counts[o.id] = Document.query.filter(
                Document.org_id == o.id, Document.deleted_at.is_(None)).count()
    return render_template('docs/hub.html', orgs=orgs, counts=counts)


@docs_bp.route('/orgs/<slug>/docs')
@login_required
def index(slug):
    org, membership = _require_org(slug)
    return render_template('docs/index.html', org=org,
                           nodes_by_parent=_build_tree(org.id),
                           doc=None, ancestors=[])


@docs_bp.route('/orgs/<slug>/docs/<int:doc_id>')
@login_required
def view(slug, doc_id):
    org, membership = _require_org(slug)
    doc = _get_doc_or_404(org, doc_id)
    return render_template('docs/index.html', org=org,
                           nodes_by_parent=_build_tree(org.id),
                           doc=doc, ancestors=_ancestors(doc))


@docs_bp.route('/orgs/<slug>/docs/<int:doc_id>/edit')
@login_required
def edit(slug, doc_id):
    org, membership = _require_org(slug)
    doc = _get_doc_or_404(org, doc_id)
    return render_template('docs/edit.html', org=org, doc=doc)


@docs_bp.route('/orgs/<slug>/docs/new', methods=['POST'])
@login_required
def create(slug):
    org, membership = _require_org(slug)
    body = request.get_json(silent=True) or request.form
    parent_id = body.get('parent_id') or None
    parent = None
    if parent_id:
        parent = (Document.query
                  .filter_by(id=parent_id, org_id=org.id)
                  .filter(Document.deleted_at.is_(None)).first())
        if parent is None:
            abort(400)
    title = (body.get('title') or 'Untitled').strip()[:255] or 'Untitled'
    sib_max = (db.session.query(func.max(Document.sort_order))
               .filter_by(org_id=org.id, parent_id=(parent.id if parent else None))
               .scalar()) or 0
    doc = Document(org_id=org.id, title=title,
                   parent_id=(parent.id if parent else None),
                   sort_order=sib_max + 1, created_by=current_user.id,
                   content='', content_html='', content_text='')
    db.session.add(doc)
    db.session.commit()
    return redirect(url_for('docs.edit', slug=org.slug, doc_id=doc.id))


# ── Mutations (AJAX / forms) ───────────────────────────────────────────────

@docs_bp.route('/api/docs/<int:doc_id>/autosave', methods=['POST'])
@login_required
def autosave(doc_id):
    doc, org, membership = _require_doc_access(doc_id)
    data = request.get_json(silent=True) or {}

    content = data.get('content') or ''
    if len(content.encode('utf-8')) > MAX_MARKDOWN_BYTES:
        return jsonify({'ok': False, 'error': 'Document too large (200 KB max).'}), 400
    title = (data.get('title') or '').strip()[:255] or 'Untitled'

    # Soft conflict: someone else saved since this editor loaded → still save
    # (last-writer-wins) but flag it so the client can warn, non-blocking.
    conflict = False
    base = data.get('base_updated_at')
    if base and doc.updated_at:
        try:
            base_dt = datetime.fromisoformat(base.replace('Z', '+00:00'))
            if base_dt.tzinfo is None:
                base_dt = base_dt.replace(tzinfo=timezone.utc)
            cur = doc.updated_at
            if cur.tzinfo is None:
                cur = cur.replace(tzinfo=timezone.utc)
            if cur > base_dt + timedelta(seconds=1):
                conflict = True
        except (ValueError, AttributeError):
            pass

    # Snapshot the pre-save state, then write.
    db.session.add(DocumentRevision(document_id=doc.id, title=doc.title,
                                    content=doc.content, edited_by=current_user.id))
    db.session.flush()

    doc.title = title
    doc.content = content
    doc.content_html = render_markdown(content)
    doc.content_text = to_plain_text(content)
    doc.updated_by = current_user.id
    if _is_postgres():
        doc.search_vector = func.to_tsvector(
            'english', f"{doc.title or ''} {doc.content_text or ''}")

    _prune_revisions(doc.id)
    db.session.commit()
    return jsonify({'ok': True, 'updated_at': doc.updated_at.isoformat(), 'conflict': conflict})


@docs_bp.route('/api/docs/reorder', methods=['POST'])
@login_required
def reorder():
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    if not items:
        return jsonify({'ok': True})

    first = Document.query.filter(Document.id == items[0].get('id')).first()
    if first is None:
        abort(404)
    org_id = first.org_id
    if not is_org_member(org_id):
        abort(404)

    for it in items:
        d = (Document.query.filter_by(id=it.get('id'), org_id=org_id)
             .filter(Document.deleted_at.is_(None)).first())
        if d is None:
            continue
        np_id = it.get('parent_id')
        if np_id is not None:
            np = Document.query.filter_by(id=np_id, org_id=org_id).first()
            if np is None or _would_cycle(d, np_id):
                continue
        d.parent_id = np_id
        if 'sort_order' in it:
            d.sort_order = it['sort_order']
    db.session.commit()
    return jsonify({'ok': True})


@docs_bp.route('/orgs/<slug>/docs/<int:doc_id>/move', methods=['POST'])
@login_required
def move(slug, doc_id):
    org, membership = _require_org(slug)
    doc = _get_doc_or_404(org, doc_id)
    raw = request.form.get('parent_id') or None
    new_parent_id = None
    if raw:
        np = (Document.query.filter_by(id=raw, org_id=org.id)
              .filter(Document.deleted_at.is_(None)).first())
        if np is None:
            flash('That destination page is not in this team.', 'danger')
            return redirect(url_for('docs.view', slug=org.slug, doc_id=doc.id))
        new_parent_id = np.id
    if _would_cycle(doc, new_parent_id):
        flash("You can't move a page inside itself.", 'danger')
        return redirect(url_for('docs.view', slug=org.slug, doc_id=doc.id))
    doc.parent_id = new_parent_id
    db.session.commit()
    flash('Page moved.', 'success')
    return redirect(url_for('docs.view', slug=org.slug, doc_id=doc.id))


@docs_bp.route('/orgs/<slug>/docs/<int:doc_id>/archive', methods=['POST'])
@login_required
def archive(slug, doc_id):
    org, membership = _require_org(slug)
    doc = _get_doc_or_404(org, doc_id)
    doc.is_archived = not doc.is_archived
    db.session.commit()
    flash('Page archived.' if doc.is_archived else 'Page restored.', 'success')
    return redirect(url_for('docs.index', slug=org.slug))


@docs_bp.route('/orgs/<slug>/docs/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete(slug, doc_id):
    org, membership = _require_org(slug)
    doc = _get_doc_or_404(org, doc_id)
    # Re-parent children so the subtree isn't orphaned, then soft-delete.
    for child in list(doc.children):
        child.parent_id = doc.parent_id
    doc.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('Page deleted.', 'success')
    return redirect(url_for('docs.index', slug=org.slug))


@docs_bp.route('/orgs/<slug>/docs/search')
@login_required
def search(slug):
    org, membership = _require_org(slug)
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'results': []})

    base = Document.query.filter(Document.org_id == org.id,
                                 Document.deleted_at.is_(None))
    if _is_postgres():
        rows = (base.filter(Document.search_vector.op('@@')(
                    func.plainto_tsquery('english', q)))
                .limit(20).all())
    else:
        like = f'%{q}%'
        rows = base.filter(or_(Document.title.ilike(like),
                               Document.content_text.ilike(like))).limit(20).all()

    return jsonify({'results': [{
        'id': d.id,
        'title': d.title,
        'snippet': (d.content_text or '')[:160],
        'url': url_for('docs.view', slug=org.slug, doc_id=d.id),
    } for d in rows]})
