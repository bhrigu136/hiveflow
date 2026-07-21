from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app.models import FileAttachment, Project, Task, Discussion, Document
from app.extensions import db
from app.authz import is_org_member
from datetime import datetime, timezone
import os

files_bp = Blueprint('files', __name__)

def check_project_access(project_id):
    """Helper to verify if current_user belongs to the project's organization."""
    if not project_id:
        return True # personal scope (e.g. personal task)
    project = Project.query.get(project_id)
    if not project:
        return False
    return is_org_member(project.org_id)

def check_document_access(document_id):
    """Verify current_user belongs to the org of the document being attached to."""
    if not document_id:
        return True
    doc = Document.query.get(document_id)
    if not doc or doc.deleted_at is not None:
        return False
    return is_org_member(doc.org_id)

def check_task_access(task_id):
    """Verify current_user may attach a file to this task.

    A project task requires membership of the owning organization. A personal
    task (no project) is private to its owner.
    """
    if not task_id:
        return True
    task = Task.query.get(task_id)
    if not task:
        return False
    if not task.project_id:
        return task.user_id == current_user.id
    project = Project.query.get(task.project_id)
    if not project:
        return False
    return is_org_member(project.org_id)

def check_discussion_access(discussion_id):
    """Verify current_user belongs to the org of the discussion's project."""
    if not discussion_id:
        return True
    discussion = Discussion.query.get(discussion_id)
    if not discussion:
        return False
    project = Project.query.get(discussion.project_id)
    if not project:
        return False
    return is_org_member(project.org_id)

@files_bp.route('/api/files/sign-upload', methods=['POST'])
@login_required
def sign_upload():
    """Generates a signed upload URL for client-side direct upload to Supabase Storage."""
    data = request.get_json() or {}
    filename = data.get('filename')
    mime_type = data.get('mime_type')
    project_id = data.get('project_id')
    document_id = data.get('document_id')

    if not filename:
        return jsonify({'error': 'Filename is required'}), 400

    if project_id and not check_project_access(project_id):
        return jsonify({'error': 'Access denied'}), 403
    if document_id and not check_document_access(document_id):
        return jsonify({'error': 'Access denied'}), 403

    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_KEY')
    bucket_name = os.environ.get('SUPABASE_STORAGE_BUCKET', 'project-assets')

    if not supabase_url or not supabase_key:
        return jsonify({'error': 'Cloud storage is not configured'}), 500

    try:
        import requests
        
        # Format a unique file path: uploads/project_<id>/user_<id>/timestamp_<filename>
        timestamp = int(datetime.now(timezone.utc).timestamp())
        if project_id:
            folder = f"project_{project_id}"
        elif document_id:
            folder = f"doc_{document_id}"
        else:
            folder = f"user_{current_user.id}"
        file_path = f"{folder}/{timestamp}_{filename}"

        # Generate signed upload URL via Supabase Storage REST API
        endpoint = f"{supabase_url}/storage/v1/object/upload/sign/{bucket_name}/{file_path}"
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json"
        }
        response = requests.post(endpoint, headers=headers, json={})
        response.raise_for_status()
        data = response.json()
        
        upload_url = data.get('url')
        if upload_url and upload_url.startswith('/'):
            upload_url = f"{supabase_url}/storage/v1{upload_url}"

        return jsonify({
            'upload_url': upload_url,
            'file_path': file_path,
            'public_url': f"{supabase_url}/storage/v1/object/public/{bucket_name}/{file_path}"
        })
    except Exception as e:
        return jsonify({'error': f'Failed to generate upload URL: {str(e)}'}), 500


@files_bp.route('/api/files/register', methods=['POST'])
@login_required
def register_file():
    """Registers a successfully uploaded file in the PostgreSQL database."""
    data = request.get_json() or {}
    filename = data.get('filename')
    file_url = data.get('file_url')
    file_size = data.get('file_size')
    mime_type = data.get('mime_type')
    
    project_id = data.get('project_id')
    task_id = data.get('task_id')
    discussion_id = data.get('discussion_id')
    document_id = data.get('document_id')

    if not filename or not file_url:
        return jsonify({'error': 'Filename and file URL are required'}), 400

    # Every scope the caller supplies must be authorized independently. Checking
    # only project_id and document_id left task_id and discussion_id open: they
    # travelled from the request body straight into the row, letting any
    # authenticated user attach a file to any task or discussion in any org.
    if project_id and not check_project_access(project_id):
        return jsonify({'error': 'Access denied'}), 403
    if document_id and not check_document_access(document_id):
        return jsonify({'error': 'Access denied'}), 403
    if task_id and not check_task_access(task_id):
        return jsonify({'error': 'Access denied'}), 403
    if discussion_id and not check_discussion_access(discussion_id):
        return jsonify({'error': 'Access denied'}), 403

    try:
        attachment = FileAttachment(
            filename=filename,
            file_url=file_url,
            file_size=file_size,
            mime_type=mime_type,
            uploaded_by=current_user.id,
            project_id=project_id,
            task_id=task_id,
            discussion_id=discussion_id,
            document_id=document_id
        )
        db.session.add(attachment)
        db.session.commit()

        return jsonify({
            'success': True,
            'file_id': attachment.id,
            'filename': attachment.filename,
            'file_url': attachment.file_url,
            'mime_type': attachment.mime_type
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to register file: {str(e)}'}), 500
