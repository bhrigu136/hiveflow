"""AI Meeting Intelligence — transcript capture, summarization, and the
'action item → assigned task' loop.

Flow:
  1. Each participant's browser POSTs final speech segments to `post_segment`.
  2. When the call ends, `finalize` assembles a speaker-labeled transcript and
     runs the (free, pluggable) summarizer to produce a summary, decisions, and
     action items.
  3. The organizer opens `review`, tweaks each action item, and `convert` turns
     it into an assigned Task on the project board — linked back to the meeting.
  4. `notes` / `notes_index` show past meetings' transcripts and summaries.

Access is gated by org membership (the same rule as joining the room). Creating
tasks / finalizing is limited to the organizer or an org Admin.
"""
from datetime import datetime, timezone, timedelta

from flask import (Blueprint, request, jsonify, render_template, redirect,
                   url_for, flash, abort, current_app)
from flask_login import login_required, current_user

from app.extensions import db, limiter, get_pusher, broadcast_event
from app.models import (Meeting, TranscriptSegment, OrgMember, Project, Task,
                        User, Organization)
from app.utils import create_notification
from app.summarizer import get_summarizer
from app.authz import get_membership

meeting_intel_bp = Blueprint('meeting_intel', __name__)


# ── Access helpers ─────────────────────────────────────────────────────────

def _require_meeting_access(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    member = get_membership(meeting.org_id)
    if member is None:
        abort(403)
    return meeting, member


def _can_manage(meeting, member):
    return meeting.created_by == current_user.id or (member and member.role == 'Admin')


def _member_choices(org_id):
    """[{'id', 'name'}] for every member of the org — assignee candidates."""
    rows = (db.session.query(User.id, User.name, User.username)
            .join(OrgMember, OrgMember.user_id == User.id)
            .filter(OrgMember.org_id == org_id).all())
    return [{'id': r[0], 'name': (r[1] or r[2])} for r in rows]


def _clamp_started(value, meeting):
    """Parse a client ISO timestamp and clamp it to the meeting window so a
    spoofed value can't reorder the transcript. Returns naive UTC."""
    now = datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat((value or '').replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    except Exception:
        dt = now

    lo = meeting.scheduled_for or now
    if lo.tzinfo is None:
        lo = lo.replace(tzinfo=timezone.utc)
    lo = lo - timedelta(hours=1)
    hi = now + timedelta(minutes=5)
    if dt < lo:
        dt = lo
    if dt > hi:
        dt = hi
    return dt.replace(tzinfo=None)


# ── 1. Live segment capture ────────────────────────────────────────────────

@meeting_intel_bp.route('/api/meetings/<int:meeting_id>/segment', methods=['POST'])
@login_required
@limiter.limit("240 per minute")
def post_segment(meeting_id):
    meeting, member = _require_meeting_access(meeting_id)

    payload = request.get_json(silent=True) or {}
    segments = payload.get('segments') or []
    if not isinstance(segments, list):
        return jsonify({'ok': False, 'error': 'bad payload'}), 400

    # Skip seqs we already stored for this (meeting, user) → idempotent retries.
    seqs = [s.get('seq') for s in segments if isinstance(s, dict) and s.get('seq') is not None]
    existing = set()
    if seqs:
        rows = (db.session.query(TranscriptSegment.seq)
                .filter(TranscriptSegment.meeting_id == meeting.id,
                        TranscriptSegment.user_id == current_user.id,
                        TranscriptSegment.seq.in_(seqs)).all())
        existing = {r[0] for r in rows}

    speaker_name = current_user.name or current_user.username
    broadcast = []
    stored = 0
    for s in segments:
        if not isinstance(s, dict):
            continue
        seq = s.get('seq')
        if seq is not None and seq in existing:
            continue
        text = (s.get('text') or '').strip()[:1000]
        if not text:
            continue
        started = _clamp_started(s.get('started_at'), meeting)
        db.session.add(TranscriptSegment(
            meeting_id=meeting.id, user_id=current_user.id,
            text=text, started_at=started, is_final=True, seq=seq))
        stored += 1
        broadcast.append({'text': text, 'started_at': started.isoformat()})

    if stored and meeting.intel_status in (None, 'none'):
        meeting.intel_status = 'recording'

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'save failed'}), 500

    # Push finals to everyone in the room for a live transcript panel.
    if broadcast:
        pusher = get_pusher()
        if pusher:
            try:
                for b in broadcast:
                    pusher.trigger(f'meeting-{meeting.id}', 'caption-final', {
                        'user_id': current_user.id,
                        'name': speaker_name,
                        'text': b['text'],
                        'started_at': b['started_at'],
                    })
            except Exception as e:
                # Best-effort live caption; segments are already stored. Broad
                # catch is intentional so a Pusher outage never breaks segment
                # ingestion; logged rather than swallowed.
                current_app.logger.warning(
                    f'[pusher] caption-final broadcast failed for meeting '
                    f'{meeting.id}: {type(e).__name__}: {e}'
                )

    return jsonify({'ok': True, 'stored': stored})


# ── 2. Finalize → summarize ────────────────────────────────────────────────

@meeting_intel_bp.route('/api/meetings/<int:meeting_id>/finalize', methods=['POST'])
@login_required
def finalize(meeting_id):
    meeting, member = _require_meeting_access(meeting_id)
    if not _can_manage(meeting, member):
        return jsonify({'ok': False, 'error': 'Only the organizer or an admin can generate notes.'}), 403

    if meeting.intel_status == 'processing':
        return jsonify({'ok': True, 'status': 'processing'})

    meeting.intel_status = 'processing'
    db.session.commit()

    try:
        transcript, speaker_ids = _assemble_transcript(meeting)
        if not transcript:
            meeting.transcript_full = ''
            meeting.summary = ''
            meeting.action_items = []
            meeting.decisions = []
            meeting.intel_status = 'ready'
            meeting.summarized_at = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify({'ok': True, 'status': 'ready', 'empty': True,
                            'redirect': url_for('meeting_intel.notes', meeting_id=meeting.id)})

        attendees = _member_choices(meeting.org_id)
        summarizer = get_summarizer()
        result = summarizer.summarize(transcript, attendees=attendees,
                                      meeting_start=meeting.scheduled_for)

        # Give each action item a stable id and an unset task link.
        items = []
        for i, it in enumerate(result.get('action_items', [])):
            it = dict(it)
            it['id'] = f'a{i}'
            it['task_id'] = None
            items.append(it)

        meeting.transcript_full = transcript
        meeting.summary = result.get('summary', '')
        meeting.action_items = items
        meeting.decisions = result.get('decisions', [])
        meeting.summarizer_engine = getattr(summarizer, 'name', 'extractive')
        meeting.summarized_at = datetime.now(timezone.utc)
        meeting.intel_status = 'ready'
        db.session.commit()
    except Exception:
        db.session.rollback()
        meeting.intel_status = 'error'
        db.session.commit()
        return jsonify({'ok': False, 'error': 'Could not generate notes.'}), 500

    create_notification(
        meeting.created_by,
        f"AI meeting notes are ready for '{meeting.title}'",
        url_for('meeting_intel.review', meeting_id=meeting.id),
    )
    db.session.commit()

    return jsonify({'ok': True, 'status': 'ready',
                    'redirect': url_for('meeting_intel.review', meeting_id=meeting.id)})


def _assemble_transcript(meeting):
    """Order every segment by start time and merge consecutive same-speaker
    lines into 'HH:MM Name: text'. Returns (transcript_text, {speaker_ids})."""
    segs = (meeting.segments
            .order_by(TranscriptSegment.started_at, TranscriptSegment.id).all())
    if not segs:
        return '', set()

    speaker_ids = {s.user_id for s in segs}
    names = {u.id: (u.name or u.username)
             for u in User.query.filter(User.id.in_(speaker_ids)).all()}

    grouped = []
    for s in segs:
        uid = s.user_id
        hhmm = s.started_at.strftime('%H:%M') if s.started_at else ''
        name = names.get(uid, 'Unknown')
        if grouped and grouped[-1]['uid'] == uid:
            grouped[-1]['text'] += ' ' + s.text
        else:
            grouped.append({'uid': uid, 'name': name, 'hhmm': hhmm, 'text': s.text})

    lines = [f"[{g['hhmm']}] {g['name']}: {g['text']}" for g in grouped]
    return '\n'.join(lines), speaker_ids


# ── 3. Review screen + convert to task ─────────────────────────────────────

@meeting_intel_bp.route('/meetings/<int:meeting_id>/review')
@login_required
def review(meeting_id):
    meeting, member = _require_meeting_access(meeting_id)
    if not _can_manage(meeting, member):
        flash('Only the organizer or an admin can review meeting notes.', 'warning')
        return redirect(url_for('meeting_intel.notes', meeting_id=meeting.id))

    org = Organization.query.get(meeting.org_id)
    projects = Project.query.filter_by(org_id=meeting.org_id).order_by(Project.name).all()
    members = _member_choices(meeting.org_id)
    return render_template('meeting_intel/review.html',
                           meeting=meeting, org=org, projects=projects,
                           members=members, action_items=meeting.action_items)


@meeting_intel_bp.route('/meetings/<int:meeting_id>/action-items/<item_id>/convert', methods=['POST'])
@login_required
def convert_action_item(meeting_id, item_id):
    meeting, member = _require_meeting_access(meeting_id)
    if not _can_manage(meeting, member):
        return jsonify({'ok': False, 'error': 'Permission denied.'}), 403

    items = meeting.action_items
    item = next((it for it in items if it.get('id') == item_id), None)
    if item is None:
        return jsonify({'ok': False, 'error': 'Action item not found.'}), 404
    if item.get('task_id'):
        return jsonify({'ok': False, 'error': 'Already converted.', 'task_id': item['task_id']}), 409

    data = request.get_json(silent=True) or request.form
    title = (data.get('title') or item.get('text') or '').strip()[:100]
    if not title:
        return jsonify({'ok': False, 'error': 'Title is required.'}), 400

    # Project must belong to this meeting's org.
    project_id = data.get('project_id')
    try:
        project_id = int(project_id) if project_id else None
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'Invalid project.'}), 400
    if not project_id:
        return jsonify({'ok': False, 'error': 'Pick a project for this task.'}), 400
    project = Project.query.filter_by(id=project_id, org_id=meeting.org_id).first()
    if project is None:
        return jsonify({'ok': False, 'error': 'That project is not in this team.'}), 400

    # Assignee (optional) must be an org member.
    assigned_to = data.get('assigned_to')
    validated_assignee = None
    if assigned_to:
        try:
            assigned_id = int(assigned_to)
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'Invalid assignee.'}), 400
        if OrgMember.query.filter_by(org_id=meeting.org_id, user_id=assigned_id).first() is None:
            return jsonify({'ok': False, 'error': 'Assignee must be a team member.'}), 400
        validated_assignee = assigned_id

    priority = (data.get('priority') or 'Medium').strip()
    deadline = _parse_date(data.get('deadline'))

    quote = item.get('source_quote') or item.get('text') or ''
    task = Task(
        title=title,
        description=f"From meeting: {meeting.title}\n\n> {quote}",
        priority=priority,
        project_id=project.id,
        user_id=current_user.id,
        created_by=current_user.id,
        assigned_to=validated_assignee,
        status='Pending',
        deadline=deadline,
        source_meeting_id=meeting.id,
    )
    db.session.add(task)
    db.session.flush()  # get task.id

    if validated_assignee and validated_assignee != current_user.id:
        create_notification(
            validated_assignee,
            f"{current_user.name or current_user.username} assigned you a task from '{meeting.title}': {title}",
            url_for('projects.dashboard', project_id=project.id),
        )

    # Record the link on the action item.
    item['task_id'] = task.id
    meeting.action_items = items
    db.session.commit()

    # Nudge the board live, consistent with discussions/comments.
    broadcast_event(
        f'project-{project.id}',
        'new-task',
        {'task_id': task.id},
        failure_desc=f'new-task broadcast failed for project {project.id}',
    )

    return jsonify({'ok': True, 'task_id': task.id,
                    'dashboard_url': url_for('projects.dashboard', project_id=project.id)})


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), '%Y-%m-%d').date()
    except (ValueError, AttributeError):
        return None


# ── 4. Notes pages ─────────────────────────────────────────────────────────

@meeting_intel_bp.route('/meetings/<int:meeting_id>/notes')
@login_required
def notes(meeting_id):
    meeting, member = _require_meeting_access(meeting_id)
    org = Organization.query.get(meeting.org_id)
    source_tasks = (Task.query.filter_by(source_meeting_id=meeting.id)
                    .order_by(Task.id.desc()).all())
    return render_template('meeting_intel/notes.html',
                           meeting=meeting, org=org,
                           source_tasks=source_tasks,
                           can_manage=_can_manage(meeting, member))


@meeting_intel_bp.route('/meetings/notes')
@login_required
def notes_index():
    # Meetings across every org the user belongs to, most recent first.
    org_ids = [m.org_id for m in
               OrgMember.query.filter_by(user_id=current_user.id).all()]
    meetings = []
    if org_ids:
        meetings = (Meeting.query
                    .filter(Meeting.org_id.in_(org_ids))
                    .order_by(Meeting.scheduled_for.desc())
                    .limit(100).all())
    return render_template('meeting_intel/notes_index.html', meetings=meetings)
